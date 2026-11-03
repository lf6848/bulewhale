@echo off
chcp 936 >nul
title DSH QQ Backup
powershell -NoProfile -ExecutionPolicy Bypass -File "D:/dsh-qq/backup.ps1"
echo.
pause
