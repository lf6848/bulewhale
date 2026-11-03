@echo off
:loop
"C:\Windows\System32\OpenSSH\ssh.exe" -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -i D:\dsh-qq\key_ssh -L 127.0.0.1:6185:127.0.0.1:6185 -L 127.0.0.1:15099:127.0.0.1:5099 -L 127.0.0.1:16081:127.0.0.1:6081 root@118.178.98.186
timeout /t 5 /nobreak >nul
goto loop
