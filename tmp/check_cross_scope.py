# -*- coding: utf-8 -*-
"""跨场景可见性实测：私聊里学到的记忆，在群聊里问得出来吗？"""
import sys
import time

sys.path.insert(0, "/opt/astrbot/data/plugins/astrbot_memory_shadow")
from engine import ShadowEngine  # noqa: E402

DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
U = "1034867860"
eng = ShadowEngine(DB)
now = int(time.time())

cases = [
    ("私聊里学到的：学校", "我在哪个城市上学", "aiocqhttp:GroupMessage:726921160"),
    ("私聊里学到的：战队", "我平时关注哪个战队", "aiocqhttp:GroupMessage:726921160"),
    ("群聊里学到的：反查私聊", "我在哪个城市上学", f"aiocqhttp:FriendMessage:{U}"),
]
for name, q, scope in cases:
    r = eng.run(user_id=U, scope=scope, text=q, write=False, now=now)
    ids = [i["id"] for i in r["injected"]]
    print(f"{name:16} scope={scope.split(':')[1]:14} q={q:12} -> ids={ids}")
    for i in r["injected"]:
        print(f"    [{i['id']}] {i['content'][:46]}")
