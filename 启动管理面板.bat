@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AstrBot 管理面板 - 118.178.98.186
cd /d "%~dp0"

set "HOST_IP=118.178.98.186"
set "SSH=%SystemRoot%\System32\OpenSSH\ssh.exe"
set "KEY=%~dp0key_ssh"
set "PORT=8770"
set "PANEL=%~dp0panel\server.ps1"
set "URL=http://127.0.0.1:%PORT%/"
set "OWNED=0"

echo.
echo   ======================================================
echo     AstrBot / SnowLuma 本地管理面板
echo     服务器 118.178.98.186
echo   ======================================================
echo.

if not exist "%SSH%" (
    echo   [错误] 找不到 Windows OpenSSH: %SSH%
    echo   请在「设置 - 应用 - 可选功能」中安装 OpenSSH 客户端。
    pause
    exit /b 1
)
if not exist "%KEY%" (
    echo   [错误] 找不到 SSH 私钥: %KEY%
    pause
    exit /b 1
)
if not exist "%PANEL%" (
    echo   [错误] 找不到面板程序: %PANEL%
    pause
    exit /b 1
)

rem ---------- 首次运行时生成桌面快捷方式 ----------
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $lnk=Join-Path $d 'AstrBot 管理面板.lnk'; if(-not (Test-Path -LiteralPath $lnk)){ $ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut($lnk); $s.TargetPath='%~f0'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,13'; $s.Description='一键启动 SSH 隧道与 AstrBot 管理面板'; $s.Save(); Write-Host '  [i] 已在桌面创建快捷方式: AstrBot 管理面板' }"

rem ---------- 面板是否已经在跑 ----------
netstat -ano | findstr /c:"127.0.0.1:%PORT%" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo   [i] 面板已经在运行，直接打开浏览器：%URL%
    start "" "%URL%"
    timeout /t 3 /nobreak >nul
    exit /b 0
)

rem ---------- 已有隧道则复用 ----------
netstat -ano | findstr /c:"127.0.0.1:16081" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 goto :tunnel_ok

echo   [1/3] 正在建立 SSH 隧道 ...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*16081:127.0.0.1:6081*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
start "" /b "%SSH%" -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -i "%KEY%" -L 127.0.0.1:6185:127.0.0.1:6185 -L 127.0.0.1:15099:127.0.0.1:5099 -L 127.0.0.1:16081:127.0.0.1:6081 root@%HOST_IP%
set "OWNED=1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; for($i=0;$i -lt 25;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',6185); $c.Close(); $ok=$true; break }catch{ Start-Sleep -Milliseconds 800 } }; if($ok){ exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo   [警告] 隧道端口未就绪，面板仍会启动，请检查网络或密钥。
) else (
    echo   [1/3] 隧道已就绪 ^(6185 / 15099 / 16081^)
)
goto :panel

:tunnel_ok
echo   [1/3] 检测到已有隧道，直接复用

:panel
echo   [2/3] 正在启动管理面板 ...
start "" "%URL%"
echo   [3/3] 面板地址: %URL%
echo.
echo   ------------------------------------------------------
echo   关闭本窗口 = 结束面板并断开 SSH 隧道
echo   ------------------------------------------------------
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PANEL%" -Port %PORT%

rem ---------- 退出时清理自己拉起的隧道 ----------
if "%OWNED%"=="1" (
    echo.
    echo   正在断开 SSH 隧道 ...
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*16081:127.0.0.1:6081*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
)
echo   已退出。
timeout /t 2 /nobreak >nul
endlocal
