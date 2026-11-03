# =====================================================================
#  AstrBot / SnowLuma 本地管理面板 —— 后端
#  只监听 127.0.0.1，数据全部通过已建立的 SSH 隧道/密钥拉取
# =====================================================================
param(
    [int]$Port = 8770,
    [string]$Root = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RemoteHost = '118.178.98.186'
$BaseDir    = Split-Path $Root -Parent
$KeyPath    = Join-Path $BaseDir 'key_ssh'
$SshExe     = Join-Path $env:SystemRoot 'System32\OpenSSH\ssh.exe'
$CacheMs    = 4000

$script:CacheTime = [datetime]::MinValue
$script:CacheBody = ''

# ---------------------------------------------------------------------
# 远端采集脚本（在服务器上由 bash 执行，输出用 ### 分节）
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
docker logs snowluma 2>&1 | grep -aE 'login detected|awaiting login|friends loaded|groups loaded|adapters=|WS-Client' | tail -n 10
echo "###BOT"
docker logs astrbot 2>&1 | grep -aE 'Loading model|适配器已连接|adapter' | tail -n 4
echo "###LOGA"
docker logs --tail 80 astrbot 2>&1 | sed -e 's/\x1b\[[0-9;]*m//g'
echo "###LOGS"
docker logs --tail 250 snowluma 2>&1 | grep -avE 'MMKV|<I> |DroppedFrame|LongTask|dbus|object_proxy|ERROR:dbus' | tail -n 70
echo "###END"
'@

# ---------------------------------------------------------------------
function Invoke-Remote {
    # 用 base64 传输远端脚本，彻底避开引号/转义问题
    $ErrorActionPreference = 'Continue'
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($RemoteScript))
    $cmd = "echo $b64 | base64 -d | bash"
    $out = & $SshExe -i $KeyPath -o BatchMode=yes -o StrictHostKeyChecking=no `
        -o UserKnownHostsFile=NUL -o ConnectTimeout=6 -o LogLevel=ERROR `
        ("root@" + $RemoteHost) $cmd 2>$null
    $code = $LASTEXITCODE
    if (-not $out) { return $null }
    $text = ($out | Out-String) -replace "`r", ''
    if ($code -ne 0 -and $text.Trim().Length -lt 10) { return $null }
    return $text
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
    if (-not $Line) { return '' }
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

    $sys   = @($sec['SYS'])
    $mem   = Field $sys[6] 0; $memUsed = Field $sys[6] 1; $memAvail = Field $sys[6] 2
    $swap  = Field $sys[7] 0; $swapUsed = Field $sys[7] 1
    $diskT = Field $sys[8] 0; $diskU = Field $sys[8] 1; $diskA = Field $sys[8] 2; $diskP = Field $sys[8] 3

    $services = New-Object System.Collections.ArrayList
    $statsMap = @{}
    foreach ($l in @($sec['STATS'])) {
        if ($l) { $statsMap[(Field $l 0)] = $l }
    }
    foreach ($l in @($sec['DOCKER'])) {
        if (-not $l) { continue }
        $name = Field $l 0
        if ($name -notin @('astrbot', 'snowluma')) { continue }
        $st = $statsMap[$name]
        $localPort = 0; $url = ''
        if ($name -eq 'astrbot')  { $localPort = 6185;  $url = 'http://127.0.0.1:6185' }
        if ($name -eq 'snowluma') { $localPort = 15099; $url = 'http://127.0.0.1:15099' }
        [void]$services.Add([ordered]@{
            name    = $name
            state   = Field $l 1
            status  = Field $l 2
            image   = Field $l 3
            cpu     = (Field $st 1)
            mem     = (Field $st 2)
            tunnel  = (Test-LocalPort $localPort)
            url     = $url
        })
    }

    # ---- 机器人信息 ----
    $qqLines = @($sec['QQ']) | Where-Object { $_ }
    $uin = ''; $friends = ''; $groups = ''; $adapters = ''; $wsState = ''; $loginState = 'unknown'
    foreach ($l in $qqLines) {
        if ($l -match 'login detected:.*UIN=(\d+)')      { $uin = $Matches[1]; $loginState = 'online' }
        elseif ($l -match 'awaiting login')               { if ($loginState -ne 'online') { $loginState = 'waiting' } }
        if ($l -match 'friends loaded:.*count=(\d+)')     { $friends = $Matches[1] }
        if ($l -match 'groups loaded:.*count=(\d+)')      { $groups = $Matches[1] }
        if ($l -match 'adapters=(\d+)')                   { $adapters = $Matches[1] }
        if ($l -match 'WS-Client\].*\] (\w+)')            { $wsState = $Matches[1] }
    }
    $botLines = @($sec['BOT']) | Where-Object { $_ }
    $model = ''; $adapterOk = $false
    foreach ($l in $botLines) {
        if ($l -match 'Loading model .*\(([^)]+)\)') { $model = $Matches[1] }
        if ($l -match '适配器已连接') { $adapterOk = $true }
    }

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
            host    = $RemoteHost
            kernel  = [string]$sys[0]
            cores   = [string]$sys[1]
            cpu     = [string]$sys[2]
            uptime  = [string]$sys[3]
            boot    = [string]$sys[4]
            load    = [string]$sys[5]
            memTotal = $mem; memUsed = $memUsed; memAvail = $memAvail
            swapTotal = $swap; swapUsed = $swapUsed
            diskTotal = $diskT; diskUsed = $diskU; diskAvail = $diskA; diskPct = $diskP
        }
        services = @($services)
        bot = [ordered]@{
            uin      = $uin
            state    = $loginState
            friends  = $friends
            groups   = $groups
            adapters = $adapters
            ws       = $wsState
            model    = $model
            adapterOk = $adapterOk
        }
        logs = [ordered]@{ astrbot = $logsA; snowluma = $logsS }
    }
    return ($status | ConvertTo-Json -Depth 8 -Compress)
}

# ---------------------------------------------------------------------
function Send-Response {
    param($Stream, [string]$Status, [string]$ContentType, [byte[]]$Body)
    $head = "HTTP/1.1 $Status`r`nContent-Type: $ContentType`r`nContent-Length: $($Body.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n`r`n"
    $hb = [System.Text.Encoding]::ASCII.GetBytes($head)
    $Stream.Write($hb, 0, $hb.Length)
    $Stream.Write($Body, 0, $Body.Length)
    $Stream.Flush()
}



try { $j = Build-Status; 'OK len=' + $j.Length; $j.Substring(0,[Math]::Min(900,$j.Length)) } catch { 'FAIL: ' + $_.Exception.Message; $_.ScriptStackTrace }
