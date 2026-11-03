# -*- coding: utf-8 -*-
"""离线桩测试：验证灰度注入、白名单、幂等与关闭开关。

测试自行创建临时 SQLite fixture，绝不读取生产记忆库。任一断言失败时必须
以非零退出，避免把打印出来的 FAIL 误当作测试通过。
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import time
import types

# ---- 造 astrbot 桩模块 ----
def _mk(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


api = _mk("astrbot.api")
root = _mk("astrbot")
root.api = api


class _Logger:
    def info(self, *a, **k):
        print("[info]", a[0] % a[1:] if len(a) > 1 else a[0])

    def warning(self, *a, **k):
        print("[warn]", a[0] % a[1:] if len(a) > 1 else a[0])

    def debug(self, *a, **k):
        pass


api.logger = _Logger()
api.AstrBotConfig = dict

event_mod = _mk("astrbot.api.event")


class AstrMessageEvent:  # noqa: D101
    pass


class _Filter:
    def on_llm_request(self):
        def deco(fn):
            return fn
        return deco

    def llm_tool(self, *a, **k):
        def deco(fn):
            return fn
        return deco


event_mod.AstrMessageEvent = AstrMessageEvent
event_mod.filter = _Filter()
api.event = event_mod

star_mod = _mk("astrbot.api.star")


class Context:  # noqa: D101
    pass


class Star:
    def __init__(self, context):
        self.context = context


def register(*a, **k):
    def deco(cls):
        return cls
    return deco


star_mod.Context = Context
star_mod.Star = Star
star_mod.register = register
api.star = star_mod

pkg = types.ModuleType("astrbot_memory_shadow")

HERE = os.path.dirname(os.path.abspath(__file__))
pkg.__path__ = [HERE]
sys.modules["astrbot_memory_shadow"] = pkg

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "astrbot_memory_shadow.main", os.path.join(HERE, "main.py"))
main_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main_mod)


class FakeEvent:
    def __init__(self, uid, text, umo=None):
        self.message_str = text
        self._uid = uid
        self.unified_msg_origin = umo or f"aiocqhttp:FriendMessage:{uid}"

    def get_sender_id(self):
        return self._uid


class FakeReq:
    def __init__(self, prompt):
        self.prompt = prompt


def run_case(plugin, uid, text, prompt="我最近熬夜看比赛了"):
    ev, rq = FakeEvent(uid, text), FakeReq(prompt)
    asyncio.run(plugin.on_llm_request(ev, rq))
    return rq.prompt


def create_fixture(db_path):
    """创建引擎查询与影子写入所需的最小 v2 SQLite 结构。"""
    now = int(time.time())
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            owner_id TEXT NOT NULL DEFAULT '',
            subject_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            content_brief TEXT NOT NULL DEFAULT '',
            type TEXT NOT NULL DEFAULT 'user_fact',
            tags TEXT NOT NULL DEFAULT '',
            importance REAL NOT NULL DEFAULT 0.7,
            created_at INTEGER NOT NULL DEFAULT 0,
            event_at INTEGER NOT NULL DEFAULT 0,
            occurrence_at INTEGER NOT NULL DEFAULT 0,
            valid_from INTEGER NOT NULL DEFAULT 0,
            valid_to INTEGER NOT NULL DEFAULT 0,
            fact_mode TEXT NOT NULL DEFAULT 'state',
            fact_key TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            superseded_by INTEGER NOT NULL DEFAULT 0,
            pinned INTEGER NOT NULL DEFAULT 0,
            visibility TEXT NOT NULL DEFAULT 'group_ok',
            allow_groups TEXT NOT NULL DEFAULT '[]',
            deleted_at INTEGER NOT NULL DEFAULT 0,
            last_reinforced_at INTEGER NOT NULL DEFAULT 0,
            initial_strength_s REAL NOT NULL DEFAULT 0,
            recall_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE memories_shadow (
            memory_id INTEGER PRIMARY KEY,
            recall_count INTEGER NOT NULL DEFAULT 0,
            last_reinforced_at INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            superseded_by INTEGER NOT NULL DEFAULT 0,
            strength_s REAL NOT NULL DEFAULT 0,
            cold INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.execute(
        "INSERT INTO memories (user_id, owner_id, subject_id, session_id, content, "
        "content_brief, type, importance, created_at, fact_key, status, visibility, "
        "last_reinforced_at, initial_strength_s) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("1034867860", "1034867860", "1034867860",
         "aiocqhttp:FriendMessage:1034867860", "对方最近常熬夜看比赛，建议规律休息。",
         "对方最近常熬夜看比赛。", "user_fact", 0.9, now, "sleep_schedule",
         "active", "owner_only", now, 86400.0),
    )
    conn.commit()
    conn.close()


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""))
    return bool(ok)


def close_fixture_connection(plugin):
    """关闭引擎缓存的 SQLite 连接，让 Windows 可以删除 TemporaryDirectory。"""
    engine = getattr(plugin, "_engine", None)
    conn = getattr(engine, "_conn", None)
    if conn is not None:
        conn.close()
        engine._conn = None


def main():
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="memory-shadow-inject-") as temp_dir:
        db_path = os.path.join(temp_dir, "memory_system.db")
        create_fixture(db_path)
        # 必须在构造插件前替换模块常量，避免实例持有生产路径的 engine。
        main_mod.DB_PATH = db_path
        plugin = None
        try:
            plugin = main_mod.MemoryShadow(Context())
            plugin._cfg["read_path_v2"] = True
            plugin._cfg["inject_user_ids"] = ["1034867860"]

            p_hit = run_case(plugin, "1034867860", "我最近熬夜看比赛了，你觉得我该注意啥")
            outcomes.append(check("A 受控用户注入", "<v2_memory>" in p_hit and "熬夜" in p_hit,
                                  "len=" + str(len(p_hit))))

            p_other = run_case(plugin, "999999999", "我最近熬夜看比赛了")
            outcomes.append(check("B 非受控用户不注入", "<v2_memory>" not in p_other))

            # 幂等：同一 prompt 再次经过不应重复追加。
            ev, rq = FakeEvent("1034867860", "我最近熬夜看比赛了"), FakeReq(p_hit)
            asyncio.run(plugin.on_llm_request(ev, rq))
            outcomes.append(check("C 重复调用幂等", rq.prompt.count("<v2_memory>") == 1))

            # 关闭开关后不注入。
            plugin._cfg["read_path_v2"] = False
            p_off = run_case(plugin, "1034867860", "我最近熬夜看比赛了")
            outcomes.append(check("D read_v2 关闭时不注入", "<v2_memory>" not in p_off))
        finally:
            if plugin is not None:
                close_fixture_connection(plugin)

    passed = all(outcomes)
    print("RESULT", "ALL PASS" if passed else "FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
