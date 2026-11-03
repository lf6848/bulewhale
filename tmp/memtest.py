import random, shutil, sqlite3, os, subprocess, sys

PROD = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
TEST = "/tmp/test_mem.db"
for p in (TEST, TEST + "-wal", TEST + "-shm"):
    if os.path.exists(p):
        os.remove(p)
_src = sqlite3.connect(PROD)
_dst = sqlite3.connect(TEST)
_src.backup(_dst)
_src.close()
_dst.close()

conn = sqlite3.connect(TEST)
conn.execute("PRAGMA journal_mode=wal")
conn.execute("PRAGMA busy_timeout=30000")

users = ["1034867860", "986823576", "2000000001"]
rows = []
important = []
for i in range(6000):
    uid = random.choice(users)
    t = random.choices(["event", "summary", "user_fact", "preference", "relationship"],
                       weights=[60, 15, 10, 10, 5])[0]
    imp = round(random.uniform(0.3, 0.95), 2)
    content = ("测试记忆内容%d：" % i) + ("闲聊记录内容填充文字。" * random.randint(10, 40))
    rows.append((uid, "session", content, t, "", imp, "auto", 1700000000 + i, 1700000000 + i, 0, 0))
    if t in ("user_fact", "preference", "relationship") and imp >= 0.6:
        important.append(i)

conn.executemany(
    "INSERT INTO memories(user_id,session_id,content,type,tags,importance,source,"
    "created_at,updated_at,last_accessed,access_count) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
conn.commit()

ps = conn.execute("PRAGMA page_size").fetchone()[0]
pc = conn.execute("PRAGMA page_count").fetchone()[0]
print("插入后: rows=%d size=%.1fMB" % (conn.execute("select count(*) from memories").fetchone()[0],
                                       ps * pc / 1024 / 1024))
conn.close()

def snapshot():
    c = sqlite3.connect(TEST)
    n = c.execute("select count(*) from memories").fetchone()[0]
    prot = c.execute(
        "select count(*) from memories where type in ('user_fact','preference','relationship') "
        "and importance >= 0.6").fetchone()[0]
    ps = c.execute("PRAGMA page_size").fetchone()[0]
    pc = c.execute("PRAGMA page_count").fetchone()[0]
    wal = os.path.getsize(TEST + "-wal") if os.path.exists(TEST + "-wal") else 0
    c.close()
    return n, prot, ps * pc, wal

print("before:", snapshot())
r = subprocess.run(["/usr/bin/python3", "/usr/local/bin/memory-prune.py",
                    "--db", TEST, "--max-mb", "6", "--target-mb", "4",
                    "--apply", "--no-notify"],
                   capture_output=True, text=True)
print(r.stdout[-2000:])
print("stderr:", r.stderr[-500:])
n, prot, size, wal = snapshot()
print("after: rows=%d 受保护画像=%d size=%.1fMB wal=%.1fMB" % (n, prot, size / 1024 / 1024, wal / 1024 / 1024))
print("受保护画像数（期望 %d）: %d" % (len(important), prot))
