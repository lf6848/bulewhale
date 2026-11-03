#Requires -Version 5.1
# 本地一键备份：在服务器打包快照，然后拉回 D:\dsh-qq\backup，本地保留最近 14 份
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$Ssh     = 'C:\Windows\System32\OpenSSH\ssh.exe'
$Scp     = 'C:\Windows\System32\OpenSSH\scp.exe'
$Key     = 'D:\dsh-qq\key_ssh'
$Host_   = 'root@118.178.98.186'
$Local   = 'D:\dsh-qq\backup'
$Keep    = 14

$common = @(
    '-o', 'BatchMode=yes',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=NUL',
    '-o', 'ConnectTimeout=15',
    '-o', 'LogLevel=ERROR',
    '-i', $Key
)

if (-not (Test-Path $Local)) { New-Item -ItemType Directory -Path $Local | Out-Null }

Write-Host '[1/3] 在服务器上打包快照...' -ForegroundColor Cyan
$remoteCmd = '/usr/local/bin/snapshot.sh >/dev/null 2>&1; ls -1t /var/backups/dsh-qq/snapshot-*.tar.gz 2>/dev/null | head -1'
$out = (& $Ssh @common $Host_ $remoteCmd 2>&1 | Out-String)
$remote = ($out -split "`n" | Where-Object { $_ -match '^/var/backups/dsh-qq/snapshot-' } | Select-Object -Last 1)
if (-not $remote) {
    Write-Host $out -ForegroundColor DarkGray
    throw '没拿到快照路径，检查 ssh 能否连上服务器'
}
$remote = $remote.Trim()
Write-Host "    $remote"

$name = Split-Path -Leaf $remote
$dest = Join-Path $Local $name

Write-Host "[2/3] 下载到 $Local ..." -ForegroundColor Cyan
$t0 = Get-Date
& $Scp @common "${Host_}:$remote" $dest
if (-not (Test-Path $dest)) { throw '下载失败，文件不存在' }
$mb = [math]::Round((Get-Item $dest).Length / 1MB, 2)
$sec = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
Write-Host "    $name  $mb MB  ${sec}s"

Write-Host '[3/4] 打包本地工作区源码（插件源码/文档/脚本）...' -ForegroundColor Cyan
$Root = 'D:\dsh-qq'
$zipName = 'workspace-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.zip'
$zipPath = Join-Path $Local $zipName
$stage = Join-Path $env:TEMP ('dshqq-stage-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$skipPat = '_braintest|_stub|\\.git\\'
$copied = 0
foreach ($d in @('docs', 'tmp', 'panel')) {
    $base = Join-Path $Root $d
    if (-not (Test-Path $base)) { continue }
    Get-ChildItem $base -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch $skipPat } | ForEach-Object {
        $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
        $target = Join-Path $stage $rel
        $dir = Split-Path $target -Parent
        try {
            if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            Copy-Item $_.FullName $target -Force -ErrorAction Stop
            $script:copied++
        } catch { }
    }
}
Get-ChildItem $Root -File -ErrorAction SilentlyContinue | Where-Object {
    ($_.Extension -in @('.ps1', '.cmd', '.bat', '.sh', '.py', '.md') -or $_.Name -eq 'sshx') -and $_.FullName -notmatch $skipPat
} | ForEach-Object {
    try { Copy-Item $_.FullName (Join-Path $stage $_.Name) -Force -ErrorAction Stop; $script:copied++ } catch { }
}
if ($copied -gt 0) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $zipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    $zmb = [math]::Round((Get-Item $zipPath).Length / 1KB, 0)
    Write-Host "    $zipName  ${zmb} KB  ($copied 个文件)"
} else {
    Write-Host '    没有可打包的源码文件' -ForegroundColor DarkGray
}
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[4/4] 本地只保留最近 $Keep 份快照 / 14 份工作区包..." -ForegroundColor Cyan
$old = Get-ChildItem $Local -Filter 'snapshot-*.tar.gz' | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep
foreach ($f in $old) {
    Remove-Item $f.FullName -Force
    Write-Host "    删除旧备份 $($f.Name)"
}
$oldZip = Get-ChildItem $Local -Filter 'workspace-*.zip' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14
foreach ($f in $oldZip) {
    Remove-Item $f.FullName -Force
    Write-Host "    删除旧源码包 $($f.Name)"
}

Write-Host ''
Get-ChildItem $Local -Filter 'snapshot-*.tar.gz' | Sort-Object LastWriteTime -Descending |
    Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}}, LastWriteTime |
    Format-Table -AutoSize | Out-String | Write-Host
