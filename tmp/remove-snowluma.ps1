$ErrorActionPreference = 'Continue'
Write-Output "=== 1) 删除计划任务 SnowLuma ==="
try {
  Unregister-ScheduledTask -TaskName 'SnowLuma' -Confirm:$false -ErrorAction Stop
  Write-Output "已删除计划任务 SnowLuma"
} catch { Write-Output "删除任务失败: $($_.Exception.Message)" }
Get-ScheduledTask | Where-Object { $_.TaskName -eq 'SnowLuma' } | Select-Object TaskName,State

Write-Output "=== 2) 停止进程 ==="
$p = Get-Process -Id 26324 -ErrorAction SilentlyContinue
if ($p) {
  try { Stop-Process -Id 26324 -Force -ErrorAction Stop; Write-Output "已结束 PID 26324" } catch { Write-Output "结束进程失败: $($_.Exception.Message)" }
} else { Write-Output "PID 26324 已不存在" }
Start-Sleep -Seconds 2
Get-Process -Id 26324 -ErrorAction SilentlyContinue | Select-Object Id,ProcessName

Write-Output "=== 3) 备份配置 ==="
$bak = "D:\dsh-qq\_backup\SnowLuma-local-20261026"
New-Item -ItemType Directory -Force -Path $bak | Out-Null
Copy-Item "C:\Users\10348\SnowLuma\config\*" -Destination $bak -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "C:\Users\10348\SnowLuma\logs" -Destination $bak -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $bak | Select-Object Name | Format-Table -AutoSize

Write-Output "=== 4) 端口 5099 状态 ==="
netstat -ano | Select-String ":5099" | Select-Object -First 3
