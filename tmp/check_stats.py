# -*- coding: utf-8 -*-
"""核对：兜底统计口径 + reinforce_ts 是否固定在 created_at + 绿龙来源。"""
import sqlite3
import sys
import time

sys.path.insert(0, "/opt/astrbot/data/plugins/astrbot_memory_shadow")
from engine import ShadowEngine  # noqa: E402

DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
U = "1034867860"
eng = ShadowEngine(DB)
now = int(time.time())
r = eng.run(user_id=U, scope=f"aiocqhttp:FriendMessage:{U}", text="我平时关注哪个战队",
            write=False, now=now)
print("ids:", [i["id"] for i in r["injected"]])
print("notes:", r["notes"])

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
row = c.execute("select id,created_at,last_reinforced_at,initial_strength_s from memories where id=68").fetchone()
print("id68 row:", dict(row) if row else None)
if row:
    print("reinforce_ts(id68) =", eng.reinforce_ts(dict(row)), "created_at =", row["created_at"])
for mid in (30, 68, 31, 9, 14, 15):
    rr = c.execute("select id,content from memories where id=?", (mid,)).fetchone()
    if rr:
        print(f"[{rr['id']}] {rr['content'][:80]}")
c.close()
