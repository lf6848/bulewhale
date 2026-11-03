@echo off
echo ==== start %DATE% %TIME% ==== >> D:\dsh-qq\tunnel.log
"C:\Windows\System32\OpenSSH\ssh.exe" -N -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -i D:\dsh-qq\id_deploy -L 127.0.0.1:6185:127.0.0.1:6185 -L 127.0.0.1:15099:127.0.0.1:5099 -L 127.0.0.1:16081:127.0.0.1:6081 root@118.178.98.186 >> D:\dsh-qq\tunnel.log 2>&1
echo ==== exit %ERRORLEVEL% at %TIME% ==== >> D:\dsh-qq\tunnel.log
