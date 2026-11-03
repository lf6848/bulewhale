#!/usr/bin/env bash
# 迁移用：在全新的 Ubuntu 22.04 上复现这台机器的主机级加固设置（幂等）
# 用法：bash host-bootstrap.sh          # 真正执行
#       bash host-bootstrap.sh --check  # 只检查不修改
set -u

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

run() {
    if [ "$CHECK" = "1" ]; then
        echo "  [check] $*"
    else
        echo "  [run]   $*"
        eval "$@" >/dev/null 2>&1 || echo "    !! 失败: $*"
    fi
}

echo "== 1. swap 4G =="
if [ -f /swapfile ] && swapon --show=NAME --noheadings 2>/dev/null | grep -q '^/swapfile$'; then
    echo "  swap 已挂载: $(swapon --show=NAME,SIZE --noheadings | grep swapfile || true)"
else
    if [ -f /swapfile ]; then
        run "chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile"
    else
        run "fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile"
    fi
fi
grep -q '/swapfile' /etc/fstab || run "echo '/swapfile none swap sw 0 0' >> /etc/fstab"

echo "== 2. vm.swappiness=10 =="
run "printf 'vm.swappiness=10\n' > /etc/sysctl.d/99-qq.conf && sysctl --system"

echo "== 3. systemd-oomd（容器内存压力兜底）=="
if dpkg -s systemd-oomd >/dev/null 2>&1; then
    echo "  已安装"
else
    run "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y systemd-oomd"
fi
run "mkdir -p /etc/systemd/system/system.slice.d"
run "printf '[Slice]\nManagedOOMMemoryPressure=kill\nManagedOOMMemoryPressureLimit=90%%\n' > /etc/systemd/system/system.slice.d/oom.conf"
run "systemctl daemon-reload && systemctl enable --now systemd-oomd && systemctl restart systemd-oomd"

echo "== 4. dockerd 挪进 docker.slice =="
run "mkdir -p /etc/systemd/system/docker.service.d"
run "printf '[Service]\nSlice=docker.slice\n' > /etc/systemd/system/docker.service.d/slice.conf"

echo "== 5. docker 镜像加速 =="
if [ -f /etc/docker/daemon.json ]; then
    echo "  已存在，跳过（避免覆盖自定义配置）"
elif [ "$CHECK" = "1" ]; then
    echo "  [check] 将写入 /etc/docker/daemon.json（5 个镜像加速）"
else
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://0vmzj3q6.mirror.aliyuncs.com",
    "https://docker.m.daocloud.io",
    "https://mirror.baidubce.com",
    "https://dockerproxy.com",
    "https://mirror.iscas.ac.cn"
  ]
}
JSON
    echo "  [run]   已写入 daemon.json"
fi
run "systemctl daemon-reload && systemctl restart docker"

echo "== 6. docker 网络 qqnet =="
if docker network inspect qqnet >/dev/null 2>&1; then
    echo "  已存在"
else
    run "docker network create qqnet"
fi

echo "== 7. 容器 cgroup 上限（容器存在才生效）=="
if docker inspect astrbot >/dev/null 2>&1; then
    run "docker update --memory 500m --memory-swap 800m astrbot"
else
    echo "  astrbot 容器还不存在，跳过（restore.sh 建好后再跑一次本脚本）"
fi
if docker inspect snowluma >/dev/null 2>&1; then
    run "docker update --memory 1000m --memory-swap 1600m snowluma"
else
    echo "  snowluma 容器还不存在，跳过"
fi

echo "== 8. cron 任务 =="
declare -a LINES=(
"40 4 * * * /usr/bin/python3 /usr/local/bin/brain-night.py >> /var/log/brain-night.log 2>&1"
"50 4 * * * /usr/local/bin/snapshot.sh >> /var/log/snapshot.log 2>&1"
"*/2 * * * * /usr/local/bin/mem-watchdog.sh >/dev/null 2>&1"
"* * * * * /usr/local/bin/health.sh >/dev/null 2>&1"
"5 4 * * * docker restart snowluma >> /var/log/mem-watchdog.log 2>&1"
"30 5 * * 7 /usr/bin/python3 /usr/local/bin/memory-prune.py --apply --max-mb 90 --target-mb 70 >> /var/log/memory-prune.log 2>&1"
)
for line in "${LINES[@]}"; do
    if crontab -l 2>/dev/null | grep -Fqx "$line"; then
        echo "  已有: ${line:0:48}…"
    else
        run "( crontab -l 2>/dev/null; echo '$line' ) | crontab -"
    fi
done

echo
echo "完成。耗时约 1 分钟；若 swap 是新挂的，可再跑一次 --check 复查。"
