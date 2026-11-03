# -*- coding: utf-8 -*-
"""在生产库上验证「删除 / 权限收紧」是否立刻生效（只插删测试行，不碰真实记忆）。"""
import sqlite3
import sys
import time

sys.path.insert(0, "/opt/astrbot/data/plugins/astrbot_memory_shadow")
from engine import ShadowEngine  # noqa: E402

DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
U = "990000001"
now = int(time.time())
friend = f"aiocqhttp:FriendMessage:{U}"
group = "aiocqhttp:GroupMessage:726921160"

c = sqlite3.connect(DB, timeout=10)
c.execute("delete from memories where user_id=?", (U,))


def add(content):
    cur = c.execute(
        "insert into memories (user_id, session_id, content, type, tags, importance, source,"
        " created_at, updated_at, last_accessed, access_count)"
        " values (?,?,?,?,?,?,?,?,?,?,?)",
        (U, friend, content, "user_fact", "[]", 0.7, "test", now, now, 0, 0),
    )
    return int(cur.lastrowid)


m1 = add("用户有一辆蓝色的山地自行车")
m2 = add("用户周末经常骑车去河边")
c.commit()

eng = ShadowEngine(DB)


def ids(text, scope):
    r = eng.run(user_id=U, scope=scope, text=text, write=False, now=now)
    return [i["id"] for i in r["injected"]]


ok = True


def check(name, cond, detail):
    global ok
    ok = ok and cond
    print(("PASS " if cond else "FAIL ") + name + " | " + detail)


a = ids("我那辆自行车是什么颜色的", friend)
check("基线：私聊能看到自己的事实", m1 in a, f"friend={a}")

c.execute("update memories set visibility='private_only' where id=?", (m1,))
c.commit()
b1 = ids("我那辆自行车是什么颜色的", friend)
b2 = ids("我那辆自行车是什么颜色的", group)
check("收紧后：私聊仍可见", m1 in b1, f"friend={b1}")
check("收紧后：群聊立即不可见（无需 scrub）", m1 not in b2, f"group={b2}")

c.execute("update memories set deleted_at=? where id=?", (now, m1))
c.commit()
d1 = ids("我那辆自行车是什么颜色的", friend)
d2 = ids("我那辆自行车是什么颜色的", group)
check("删除后：私聊立即不可见", m1 not in d1, f"friend={d1}")
check("删除后：群聊立即不可见", m1 not in d2, f"group={d2}")

c.execute("delete from memories where user_id=?", (U,))
c.commit()
left = c.execute("select count(*) from memories where user_id=?", (U,)).fetchone()[0]
check("清理测试行", left == 0, f"left={left}")
c.close()
print("RESULT", "ALL PASS" if ok else "HAS FAIL")
