#!/bin/bash
# DSH QQ 部署快照：把插件/配置/脚本/cron/docker 参数打成一个 tar.gz
# 用法: snapshot.sh [--no-data]
set -euo pipefail

DEST=/var/backups/dsh-qq
KEEP=5
WITH_DATA=1
[ "${1:-}" = "--no-data" ] && WITH_DATA=0

mkdir -p "$DEST"
ts=$(date +%Y%m%d-%H%M%S)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work"/{bin,meta,data}

# 1. AstrBot 插件 / 配置（plugin_data 里 meme_manager/packs 是表情包图片，几百 MB，不进快照）
cp -a /opt/astrbot/data/plugins "$work"/plugins
cp -a /opt/astrbot/data/config "$work"/config
cp -a /opt/astrbot/data/cmd_config.json "$work"/cmd_config.json
[ -d /opt/astrbot/data/plugin_data ] && tar cf - --exclude='packs' -C /opt/astrbot/data plugin_data | tar xf - -C "$work"

# 2. 宿主机脚本
for f in /usr/local/bin/health.sh /usr/local/bin/mem-watchdog.sh /usr/local/bin/memory-prune.py /usr/local/bin/snapshot.sh /usr/local/bin/restore.sh; do
    [ -f "$f" ] && cp -a "$f" "$work"/bin/
done

# 3. cron / docker 参数 / 版本信息
crontab -l > "$work"/meta/crontab.txt 2>/dev/null || true
docker inspect astrbot snowluma > "$work"/meta/docker-inspect.json 2>/dev/null || true
docker network inspect qqnet > "$work"/meta/network-qqnet.json 2>/dev/null || true
{
    echo "# 生成时间: $ts"
    echo "# 恢复时按需执行下面两条（卷名、端口、cgroup 限制都在里面）"
    echo "## astrbot"
    echo 'docker run -d --name astrbot --restart unless-stopped --network qqnet -e TZ=Asia/Shanghai -p 127.0.0.1:6185:6185 -p 127.0.0.1:6199:6199 -v /opt/astrbot/data:/AstrBot/data -v /etc/localtime:/etc/localtime:ro soulter/astrbot:latest'
    echo "## snowluma"
    echo 'docker run -d --name snowluma --restart unless-stopped --network qqnet --shm-size=1g --ulimit nofile=65536:1048576 --cap-add=SYS_PTRACE --security-opt seccomp=unconfined -e TZ=Asia/Shanghai -e VNC_PASSWD=snow2026 -e SNOWLUMA_WEBUI_HOST=0.0.0.0 -e SNOWLUMA_WEBUI_PORT=5099 -e SNOWLUMA_QQ_FLAGS="--disable-gpu --disable-software-rasterizer --disable-gpu-compositing" -p 127.0.0.1:6081:6081 -p 127.0.0.1:5900:5900 -p 127.0.0.1:5099:5099 -p 127.0.0.1:3000:3000 -p 127.0.0.1:3001:3001 -v qq-gateway-data:/app/data -v qq-client-config:/app/.config -v qq-client-data:/app/.local/share motricseven7/snowluma:latest'
    echo "## cgroup 限制（启动后补）"
    echo 'docker update --memory 500m --memory-swap 800m astrbot'
    echo 'docker update --memory 1000m --memory-swap 1600m snowluma'
} > "$work"/meta/restore-docker.sh
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$work"/meta/containers.txt 2>/dev/null || true

# 4. 数据（可选）
if [ "$WITH_DATA" = "1" ]; then
    for f in data_v4.db data_v4.db-wal data_v4.db-shm; do
        [ -f "/opt/astrbot/data/$f" ] && cp -a "/opt/astrbot/data/$f" "$work"/data/
    done
    [ -f /opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db ] && \
        cp -a /opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db "$work"/data/
fi

out="$DEST/snapshot-$ts.tar.gz"
tar czf "$out" -C "$work" .
chmod 600 "$out"

# 5. 轮转
ls -1t "$DEST"/snapshot-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "$out"
du -h "$out" | awk '{print "size: "$1}'
