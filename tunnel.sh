#!/bin/bash
# SSH tunnel: local 6185 -> AstrBot, 15099 -> SnowLuma WebUI, 16081 -> noVNC
pkill -f "15099:127.0.0.1:5099" 2>/dev/null
sleep 1
exec ssh -f -N \
  -o ExitOnForwardFailure=yes \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -i /d/dsh-qq/id_deploy \
  -L 127.0.0.1:6185:127.0.0.1:6185 \
  -L 127.0.0.1:15099:127.0.0.1:5099 \
  -L 127.0.0.1:16081:127.0.0.1:6081 \
  root@118.178.98.186
