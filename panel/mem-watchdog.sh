#!/bin/sh
# mem-watchdog: 内存压力过大时自动重启 SnowLuma 容器，避免整机 thrash 卡死
# 由 cron 每 2 分钟调用一次。阈值按 1.7G 内存 + 4G swap 设定。
LOG=/var/log/mem-watchdog.log
STATE=/var/lib/mem-watchdog.last
AVAIL_MIN=110        # 可用内存低于 110MB 视为危险
SWAP_MAX=1600        # swap 已用超过 1600MB 视为危险
COOLDOWN=1200        # 一次重启后 20 分钟内不再重启，避免抖动循环

ts() { date '+%Y-%m-%d %H:%M:%S'; }
meminfo() {
    avail=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
    swapused=$(awk '/^SwapTotal:/{t=$2} /^SwapFree:/{f=$2} END{print int((t-f)/1024)}' /proc/meminfo)
}

meminfo
crit=0
[ "$avail" -lt "$AVAIL_MIN" ] && crit=1
[ "$swapused" -gt "$SWAP_MAX" ] && crit=1

if [ "$crit" -eq 0 ]; then
    exit 0
fi

now=$(date +%s)
if [ -f "$STATE" ]; then
    last=$(cat "$STATE" 2>/dev/null)
    case "$last" in
        ''|*[!0-9]*) last=0 ;;
    esac
    if [ $((now - last)) -lt "$COOLDOWN" ]; then
        echo "$(ts) WARN avail=${avail}MB swap=${swapused}MB (cooldown, skip)" >> "$LOG"
        exit 0
    fi
fi
echo "$now" > "$STATE"

echo "$(ts) WARN avail=${avail}MB swap=${swapused}MB -> docker restart snowluma" >> "$LOG"
docker restart snowluma >> "$LOG" 2>&1
sleep 90

meminfo
if [ "$avail" -lt "$AVAIL_MIN" ]; then
    echo "$(ts) CRITICAL avail=${avail}MB swap=${swapused}MB -> docker restart astrbot" >> "$LOG"
    docker restart astrbot >> "$LOG" 2>&1
    sleep 30
    meminfo
fi
echo "$(ts) recovered avail=${avail}MB swap=${swapused}MB" >> "$LOG"

# 日志只保留最近 400 行
if [ "$(wc -l < "$LOG")" -gt 400 ]; then
    tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
exit 0
