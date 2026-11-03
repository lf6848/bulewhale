@echo off
rem silent pull of latest snapshot (called by Startup shortcut)
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:/dsh-qq/backup.ps1" >> "D:/dsh-qq/backup/backup.log" 2>&1
