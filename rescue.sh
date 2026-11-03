#!/bin/bash
KEY=/d/dsh-qq/id_deploy
HOST=root@118.178.98.186
OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o ConnectTimeout=8 -o ServerAliveInterval=10 -o ServerAliveCountMax=2"

probe() {
  timeout 15 ssh $OPTS -i "$KEY" "$HOST" 'echo ALIVE' 2>/dev/null | grep -q ALIVE
}

for i in $(seq 1 28); do
  if probe; then
    echo "=== CONNECTED on try $i ==="
    timeout 60 ssh $OPTS -i "$KEY" "$HOST" '
      echo "--- before ---"; free -m | head -3; uptime
      docker stats --no-stream --format "{{.Name}} {{.MemUsage}} {{.CPUPerc}}"
      echo "--- restarting snowluma ---"
      docker restart snowluma
      sleep 8
      echo "--- after ---"; free -m | head -3
      docker ps --format "{{.Names}} {{.Status}}"
      echo "--- oom ---"; dmesg -T 2>/dev/null | grep -iE "oom-kill|killed process|out of memory" | tail -4
    ' 2>&1
    exit 0
  fi
  echo "try $i: no banner"
  sleep 8
done
echo "=== gave up after 28 tries ==="
exit 1
