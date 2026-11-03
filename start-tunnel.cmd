@echo off
title Start DSH QQ tunnel
schtasks /run /tn "dshqq-tunnel" >nul 2>&1
timeout /t 4 /nobreak >nul
netstat -ano | findstr /C:":6185" | findstr LISTENING >nul 2>&1
if not errorlevel 1 goto ok
echo [..] task path failed, starting ssh directly
start "dshtunnel" /min "D:\dsh-qq\tunnel-run.cmd"
timeout /t 6 /nobreak >nul
netstat -ano | findstr /C:":6185" | findstr LISTENING >nul 2>&1
if not errorlevel 1 goto ok
echo.
echo [FAIL] port 6185 not listening. Check D:\dsh-qq\key_ssh and server state.
echo.
pause
exit /b 1
:ok
echo.
echo [OK] tunnel up: astrbot 6185 / snowluma 15099 / novnc 16081
echo.
pause
exit /b 0
