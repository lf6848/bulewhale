#!/bin/bash
# 从快照 tar.gz 恢复（在新机器/摔坏之后用）
# 用法: restore.sh /var/backups/dsh-qq/snapshot-YYYYmmdd-HHMMSS.tar.gz
set -euo pipefail

[ $# -eq 1 ] || { echo "用法: $0 <snapshot.tar.gz>"; exit 1; }
tar="$1"
[ -f "$tar" ] || { echo "找不到: $tar"; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
tar xzf "$tar" -C "$work"
echo "== 快照内容"; ls -1 "$work"

echo "== 停止容器"
docker stop astrbot snowluma >/dev/null 2>&1 || true

echo "== 恢复插件与配置"
mkdir -p /opt/astrbot/data
rm -rf /opt/astrbot/data/plugins
cp -a "$work"/plugins /opt/astrbot/data/plugins
cp -a "$work"/config/. /opt/astrbot/data/config/
cp -a "$work"/cmd_config.json /opt/astrbot/data/cmd_config.json
[ -d "$work"/plugin_data ] && cp -a "$work"/plugin_data/. /opt/astrbot/data/plugin_data/

if [ -d "$work"/data ]; then
    echo "== 恢复数据库"
    cp -a "$work"/data/. /opt/astrbot/data/
fi

echo "== 恢复宿主机脚本"
cp -a "$work"/bin/. /usr/local/bin/ 2>/dev/null || true
chmod +x /usr/local/bin/*.sh 2>/dev/null || true

echo "== 恢复 crontab"
if [ -f "$work"/meta/crontab.txt ]; then
    crontab "$work"/meta/crontab.txt
fi

echo "== 重启容器"
docker start snowluma astrbot >/dev/null 2>&1 || {
    echo "容器不存在，需要按 meta/restore-docker.sh 重建："
    cat "$work"/meta/restore-docker.sh
}
echo "完成。检查：docker ps; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6185"
