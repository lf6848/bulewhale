#!/bin/bash
echo "=== free ==="
free -m
echo
echo "=== swap ==="
swapon --show
echo
echo "=== docker stats ==="
docker stats --no-stream --format "table {{{{.Name}}}}\t{{{{.MemUsage}}}}\t{{{{.MemPerc}}}}\t{{{{.CPUPerc}}}}"
echo
echo "=== cgroup ==="
for c in snowluma astrbot; do
  id=$(docker inspect -f '{{.Id}}' "$c")
  base=/sys/fs/cgroup/system.slice/docker-$id.scope
  cur=$(cat "$base/memory.current" 2>/dev/null)
  max=$(cat "$base/memory.max" 2>/dev/null)
  echo "$c: current=$((cur/1048576))MiB max=$((max/1048576))MiB"
done
echo
echo "=== top processes ==="
ps -eo rss,comm --sort=-rss | head -6
