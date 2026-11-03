import io, re, shutil, time

ts = time.strftime("%Y%m%d-%H%M%S")

# ---------- snapshot.sh ----------
p = "/usr/local/bin/snapshot.sh"
shutil.copy(p, p + ".bak-" + ts)
s = io.open(p, encoding="utf-8").read()

old = '''    [ -f /opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db ] && \\
        cp -a /opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db "$work"/data/'''
new = '''    # 长期记忆库是 WAL 模式：只拷 .db 会丢掉未 checkpoint 的记忆，必须连 -wal/-shm 一起拷
    for f in memory_system.db memory_system.db-wal memory_system.db-shm; do
        [ -f "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/$f" ] && \\
            cp -a "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/$f" "$work"/data/
    done'''
assert old in s, "snapshot.sh pattern not found"
io.open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("[ok] snapshot.sh patched")

# ---------- restore.sh ----------
p2 = "/usr/local/bin/restore.sh"
shutil.copy(p2, p2 + ".bak-" + ts)
r = io.open(p2, encoding="utf-8").read()

old2 = '''cp -a "$work"/cmd_config.json /opt/astrbot/data/cmd_config.json
[ -d "$work"/plugin_data ] && cp -a "$work"/plugin_data/. /opt/astrbot/data/plugin_data/

if [ -d "$work"/data ]; then
    echo "== 恢复数据库"
    cp -a "$work"/data/. /opt/astrbot/data/
fi'''
new2 = '''cp -a "$work"/cmd_config.json /opt/astrbot/data/cmd_config.json

# 注意顺序：先还原 data/（含 data_v4.db 与旧格式备份），再还原 plugin_data/
# 后者带 -wal/-shm，是最新的长期记忆，绝不能被 data/ 里的旧 .db 覆盖
if [ -d "$work"/data ]; then
    echo "== 恢复数据库"
    cp -a "$work"/data/. /opt/astrbot/data/
fi
[ -d "$work"/plugin_data ] && cp -a "$work"/plugin_data/. /opt/astrbot/data/plugin_data/'''
assert old2 in r, "restore.sh pattern not found"
io.open(p2, "w", encoding="utf-8").write(r.replace(old2, new2))
print("[ok] restore.sh patched")
