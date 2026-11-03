#!/bin/sh
# health-log: 每分钟记录一次资源快照，用于事后定位卡死原因
LOG=/var/log/health.log
ts=$(date '+%Y-%m-%d %H:%M:%S')
line="$ts | mem: $(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^SwapTotal:/{st=$2} /^SwapFree:/{sf=$2} END{printf "total=%dM avail=%dM swap=%d/%dM", t/1024, a/1024, (st-sf)/1024, st/1024}' /proc/meminfo) | load: $(cut -d' ' -f1-3 /proc/loadavg) | psin: $(awk '/^procs_running/{print $2}' /proc/stat)"
for c in astrbot snowluma; do
    mem=$(docker stats --no-stream --format '{{.MemUsage}}' "$c" 2>/dev/null | awk '{print $1}')
    cpu=$(docker stats --no-stream --format '{{.CPUPerc}}' "$c" 2>/dev/null)
    line="$line | $c=$mem/$cpu"
done
top3=$(ps -eo pcpu,rss,comm --sort=-pcpu 2>/dev/null | head -4 | tail -3 | awk '{printf "%s:%s%%/%dM ", $3, $1, $2/1024}')
line="$line | top: $top3"
echo "$line" >> "$LOG"

if [ "$(wc -l < "$LOG")" -gt 3000 ]; then
    tail -n 1500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exit 0
