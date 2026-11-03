@echo off
chcp 936 >nul
rem pull the newest snapshot every 6 hours while logged in
:loop
call "D:\dsh-qq\backup-silent.cmd"
timeout /t 21600 /nobreak >nul
goto loop
