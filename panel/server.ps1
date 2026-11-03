# =====================================================================
#  AstrBot / SnowLuma local management panel - backend
#  Listens on 127.0.0.1 only. All data is pulled over SSH.
#  NOTE: keep this file pure ASCII so no editor can break its encoding.
# =====================================================================
param(
    [int]$Port = 8770,
    [string]$Root = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$RemoteHost = '118.178.98.186'
$BaseDir    = Split-Path $Root -Parent
$KeyPath    = Join-Path $BaseDir 'key_ssh'
$SshExe     = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$CacheMs    = 4000

$script:CacheTime = [datetime]::MinValue
$script:CacheBody = ''

# ---------------------------------------------------------------------
# Remote collector (runs under bash on the server, sections marked ###)
# ---------------------------------------------------------------------
$RemoteScript = @'
LC_ALL=C
echo "###SYS"
uname -sr
nproc
grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | sed 's/^ *//'
uptime -p 2>/dev/null || uptime
uptime -s 2>/dev/null || echo "-"
cut -d' ' -f1-3 /proc/loadavg
free -m | awk '/^Mem:/{print $2"|"$3"|"$7}'
free -m | awk '/^Swap:/{print $2"|"$3}'
df -h / | awk 'NR==2{print $2"|"$3"|"$4"|"$5}'
echo "###DOCKER"
docker ps -a --format '{{.Names}}|{{.State}}|{{.Status}}|{{.Image}}' 2>/dev/null
echo "###STATS"
docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' 2>/dev/null
echo "###QQ"
docker logs snowluma 2>&1 | grep -aE 'login detected|awaiting login|friends loaded|groups loaded|adapters=|WS-Client' | tail -n 12
echo "###MODEL"
grep -m1 -o '"model": "[^"]*' /opt/astrbot/data/cmd_config.json 2>/dev/null | sed 's/.*: "//'
echo "###LOGA"
docker logs --tail 80 astrbot 2>&1 | sed -e 's/\x1b\[[0-9;]*m//g'
echo "###LOGS"
docker logs --tail 250 snowluma 2>&1 | grep -avE 'MMKV|<I> |DroppedFrame|LongTask|dbus|object_proxy|ERROR:dbus|ERROR:gpu' | tail -n 70
echo "###END"
'@

# ---------------------------------------------------------------------
function Invoke-Remote {
    # base64 keeps the remote script immune to quoting/escaping issues
    $ErrorActionPreference = 'Continue'
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($RemoteScript))
    $cmd = "echo $b64 | base64 -d | bash"
    $out = & $SshExe -i $KeyPath -o BatchMode=yes -o StrictHostKeyChecking=no `
        -o UserKnownHostsFile=NUL -o ConnectTimeout=6 -o LogLevel=ERROR `
        ("root@" + $RemoteHost) $cmd 2>$null
    if (-not $out) { return $null }
    return (($out | Out-String) -replace "`r", '')
}

function Test-LocalPort {
    param([int]$Port)
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect('127.0.0.1', $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(600) -and $c.Connected) { return $true }
        return $false
    } catch { return $false } finally { $c.Close() }
}

function Split-Sections {
    param([string]$Raw)
    $map = @{}
    $cur = ''
    $buf = New-Object System.Collections.ArrayList
    foreach ($line in ($Raw -split "`n")) {
        if ($line -match '^###([A-Z]+)\s*$') {
            if ($cur) { $map[$cur] = @($buf) }
            $cur = $Matches[1]
            $buf = New-Object System.Collections.ArrayList
        } elseif ($cur) {
            [void]$buf.Add($line)
        }
    }
    if ($cur) { $map[$cur] = @($buf) }
    return $map
}

function Field {
    param($Line, [int]$Index)
    if ($null -eq $Line -or $Line -eq '') { return '' }
    $parts = ([string]$Line) -split '\|'
    if ($Index -lt $parts.Length) { return $parts[$Index].Trim() }
    return ''
}

# ---------------------------------------------------------------------
function Build-Status {
    $raw = Invoke-Remote
    $ok = [bool]$raw
    $sec = @{}
    if ($ok) { $sec = Split-Sections -Raw $raw }

    $sys  = @($sec['SYS'])
    $mem      = Field $sys[6] 0
    $memUsed  = Field $sys[6] 1
    $swap     = Field $sys[7] 0
    $swapUsed = Field $sys[7] 1
    $diskT    = Field $sys[8] 0
    $diskU    = Field $sys[8] 1
    $diskP    = Field $sys[8] 3

    $services = New-Object System.Collections.ArrayList
    $statsMap = @{}
    foreach ($l in @($sec['STATS'])) {
        if ($l) { $statsMap[(Field $l 0)] = $l }
    }
    foreach ($l in @($sec['DOCKER'])) {
        if (-not $l) { continue }
        $name = Field $l 0
        if (($name -ne 'astrbot') -and ($name -ne 'snowluma')) { continue }
        $st = $statsMap[$name]
        $localPort = 0
        $url = ''
        if ($name -eq 'astrbot')  { $localPort = 6185;  $url = 'http://127.0.0.1:6185' }
        if ($name -eq 'snowluma') { $localPort = 15099; $url = 'http://127.0.0.1:15099' }
        [void]$services.Add([ordered]@{
            name   = $name
            state  = (Field $l 1)
            status = (Field $l 2)
            image  = (Field $l 3)
            cpu    = (Field $st 1)
            mem    = (Field $st 2)
            tunnel = (Test-LocalPort $localPort)
            url    = $url
        })
    }

    # ---- bot info ----
    $qqLines = @($sec['QQ']) | Where-Object { $_ }
    $uin = ''; $friends = ''; $groups = ''; $adapters = ''; $wsState = ''; $loginState = 'unknown'
    foreach ($l in $qqLines) {
        if ($l -match 'login detected:.*UIN=(\d+)') {
            $uin = $Matches[1]
            $loginState = 'online'
        } elseif ($l -match 'awaiting login') {
            if ($loginState -ne 'online') { $loginState = 'waiting' }
        }
        if ($l -match 'friends loaded:.*count=(\d+)') { $friends = $Matches[1] }
        if ($l -match 'groups loaded:.*count=(\d+)')  { $groups  = $Matches[1] }
        if ($l -match 'adapters=(\d+)')               { $adapters = $Matches[1] }
        if ($l -match 'WS-Client\].*\]\s+(\w+)')      { $wsState = $Matches[1] }
    }
    $model = ''
    $mLine = @($sec['MODEL']) | Where-Object { $_ } | Select-Object -First 1
    if ($mLine) { $model = ([string]$mLine).Trim() }

    $logsA = @($sec['LOGA']) | Where-Object { $_ -ne $null }
    $logsS = @($sec['LOGS']) | Where-Object { $_ -ne $null }

    $status = [ordered]@{
        ts   = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        ok   = $ok
        tunnel = [ordered]@{
            astrbot  = (Test-LocalPort 6185)
            snowluma = (Test-LocalPort 15099)
            novnc    = (Test-LocalPort 16081)
        }
        server = [ordered]@{
            host      = $RemoteHost
            kernel    = [string]$sys[0]
            cores     = [string]$sys[1]
            cpu       = [string]$sys[2]
            uptime    = [string]$sys[3]
            boot      = [string]$sys[4]
            load      = [string]$sys[5]
            memTotal  = $mem
            memUsed   = $memUsed
            memAvail  = (Field $sys[6] 2)
            swapTotal = $swap
            swapUsed  = $swapUsed
            diskTotal = $diskT
            diskUsed  = $diskU
            diskAvail = (Field $sys[8] 2)
            diskPct   = $diskP
        }
        services = @($services)
        bot = [ordered]@{
            uin       = $uin
            state     = $loginState
            friends   = $friends
            groups    = $groups
            adapters  = $adapters
            ws        = $wsState
            model     = $model
            adapterOk = ($wsState -eq 'connected')
        }
        logs = [ordered]@{ astrbot = $logsA; snowluma = $logsS }
    }
    return ($status | ConvertTo-Json -Depth 8 -Compress)
}

# ---------------------------------------------------------------------
function Send-Response {
    param($Stream, [string]$StatusText, [string]$ContentType, [byte[]]$Body)
    $head = "HTTP/1.1 $StatusText`r`nContent-Type: $ContentType`r`nContent-Length: $($Body.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
    $hb = [System.Text.Encoding]::ASCII.GetBytes($head)
    $Stream.Write($hb, 0, $hb.Length)
    $Stream.Write($Body, 0, $Body.Length)
    $Stream.Flush()
}

$listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
$listener.Start()
Write-Host ''
Write-Host ('  Panel ready  -> http://127.0.0.1:{0}/' -f $Port) -ForegroundColor Cyan
Write-Host '  Close this window to stop the panel and the SSH tunnel.' -ForegroundColor DarkGray
Write-Host ''

$utf8 = New-Object System.Text.UTF8Encoding($false)

while ($true) {
    $client = $null
    try {
        $client = $listener.AcceptTcpClient()
        $client.ReceiveTimeout = 8000
        $client.SendTimeout = 20000
        $stream = $client.GetStream()
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::ASCII)
        $requestLine = $reader.ReadLine()
        if (-not $requestLine) { continue }
        $guard = 0
        while ($guard -lt 60) {
            $h = $reader.ReadLine()
            $guard++
            if ($null -eq $h -or $h -eq '') { break }
        }
        $parts = $requestLine -split ' '
        $path = '/'
        if ($parts.Length -ge 2) { $path = $parts[1] }
        $path = ($path -split '\?')[0]

        if ($path -eq '/' -or $path -eq '/index.html') {
            $file = Join-Path $Root 'index.html'
            if (Test-Path $file) {
                Send-Response $stream '200 OK' 'text/html; charset=utf-8' ([System.IO.File]::ReadAllBytes($file))
            } else {
                Send-Response $stream '404 Not Found' 'text/plain; charset=utf-8' ($utf8.GetBytes('index.html missing'))
            }
        }
        elseif ($path -eq '/api/status') {
            $now = Get-Date
            if (($now - $script:CacheTime).TotalMilliseconds -gt $CacheMs) {
                try {
                    $script:CacheBody = Build-Status
                } catch {
                    $msg = ([string]$_.Exception.Message) -replace '\\', '/' -replace '"', "'" -replace "`r", ' ' -replace "`n", ' '
                    $script:CacheBody = '{"ok":false,"error":"' + $msg + '","services":[],"logs":{},"tunnel":{},"server":{},"bot":{}}'
                }
                $script:CacheTime = $now
            }
            Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes($script:CacheBody))
            Write-Host ('  [{0}] /api/status {1} bytes' -f $now.ToString('HH:mm:ss'), $script:CacheBody.Length) -ForegroundColor DarkGray
        }
        elseif ($path -eq '/api/ping') {
            Send-Response $stream '200 OK' 'application/json; charset=utf-8' ($utf8.GetBytes('{"ok":true}'))
        }
        else {
            Send-Response $stream '404 Not Found' 'text/plain; charset=utf-8' ($utf8.GetBytes('not found'))
        }
    } catch {
        # ignore per-request failures
    } finally {
        if ($client) { try { $client.Close() } catch { } }
    }
}
