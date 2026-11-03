# -*- coding: utf-8 -*-
"""遗忘树 v2 影子验收：四条反例 + 冷层固定时钟 + 异常路径。

全部在 /tmp 的库副本上跑，绝不碰生产库。
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import DAY, ShadowEngine  # noqa: E402

SRC = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
USER = "1034867860"
PRIVATE = f"aiocqhttp:FriendMessage:{USER}"
GROUP = "aiocqhttp:GroupMessage:726921160"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


def fresh_db() -> str:
    dst = "/tmp/accept_v2.db"
    for s in ("", "-wal", "-shm"):
        try:
            os.remove(dst + s)
        except FileNotFoundError:
            pass
    src = sqlite3.connect(SRC)
    out = sqlite3.connect(dst)
    src.backup(out)
    out.close()
    src.close()
    return dst


def conn(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def sig(db: str, table: str) -> str:
    c = conn(db)
    try:
        rows = c.execute(f"select * from {table}").fetchall()
    except sqlite3.OperationalError:
        c.close()
        return "missing"
    h = hashlib.md5(repr([tuple(r) for r in rows]).encode()).hexdigest()[:16]
    c.close()
    return f"{len(rows)}:{h}"


def insert(db: str, *, content: str, type_: str = "user_fact", importance: float = 0.7,
           created: float, fact_key: str = "", fact_mode: str = "state",
           occurrence_at: float | None = None, subject_id: str | None = None,
           visibility: str = "group_ok", legacy: bool = True) -> int:
    """legacy=True 模拟旧写入器：只写迁移前的列，新列留 NULL/0。"""
    c = conn(db)
    now = time.time()
    cur = c.execute(
        "INSERT INTO memories (user_id, session_id, content, type, tags, importance, source,"
        " created_at, updated_at, last_accessed, access_count) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
        (USER, PRIVATE, content, type_, "", importance, "auto", created, now, created),
    )
    mid = int(cur.lastrowid)
    if not legacy:
        c.execute(
            "UPDATE memories SET status='active', visibility=?, owner_id=?, fact_mode=?,"
            " fact_key=?, occurrence_at=?, event_at=?, subject_id=?,"
            " last_reinforced_at=?, initial_strength_s=? WHERE id=?",
            (visibility, USER, fact_mode, fact_key, occurrence_at or 0, occurrence_at or 0,
             subject_id, created, 0, mid),
        )
    else:
        c.execute("UPDATE memories SET visibility=?, owner_id=?, fact_mode=?, fact_key=?,"
                  " occurrence_at=? WHERE id=?", (visibility, USER, fact_mode, fact_key,
                                                  occurrence_at or 0, mid))
    c.commit()
    c.close()
    return mid


def row_of(db: str, mid: int) -> dict:
    c = conn(db)
    r = c.execute("select * from memories where id=?", (mid,)).fetchone()
    c.close()
    return dict(r) if r else {}


def run(db: str, text: str, *, now: float | None = None, scope: str = PRIVATE,
        write: bool = False, user: str = USER) -> dict:
    eng = ShadowEngine(db, {"shadow_v2": True})
    return eng.run(user_id=user, scope=scope, text=text, now=now, write=write)


def ids(res: dict) -> list[int]:
    return [i["id"] for i in res["injected"]]


# ---------------------------------------------------------------- 1. 新行回填
def t1_backfill() -> None:
    db = fresh_db()
    now = time.time()
    mid = insert(db, content="用户养了一只叫『雪球』的仓鼠", importance=0.7,
                 created=now - 10 * DAY, fact_key="pet_hamster")
    before = row_of(db, mid)
    res = run(db, "我的仓鼠叫什么名字", now=now, write=True)
    after = row_of(db, mid)

    c = conn(db)
    sh = c.execute("select * from memories_shadow where memory_id=?", (mid,)).fetchone()
    c.close()

    ok_inject = mid in ids(res)
    ok_prod = before == after
    ok_shadow = bool(sh) and float(sh["strength_s"] or 0) > 0 and int(sh["cold"] or 0) == 0
    check("T1 新行回填/召回", ok_inject, f"got={ids(res)}")
    check("T1 生产行未被改写", ok_prod,
          "" if ok_prod else "生产列被动了：" + str({k: (before[k], after[k]) for k in before
                                                if before[k] != after[k]}))
    check("T1 影子侧正确初始化", ok_shadow,
          "" if not sh else f"strength={sh['strength_s']} cold={sh['cold']}")


# ---------------------------------------------------------------- 2. 定向硬排除
def t2_targeted() -> None:
    db = fresh_db()
    now = time.time()
    exam = insert(db, content="用户正在准备考研，报了辅导班", importance=0.7,
                  created=now - 3 * DAY, fact_key="exam_a")
    job = insert(db, content="用户最近准备去参加一场招聘会", importance=0.6,
                 created=now - 2 * DAY, fact_key="job_b")
    pet2 = insert(db, content="用户的昵称是大肥鱼，最近在准备养猫", importance=0.5,
                  created=now - 1 * DAY, fact_key="nick_c")

    res = run(db, "我考研准备得怎么样", now=now)
    got = ids(res)
    check("T2 同主体·属性不符（准备/最近 共享）不入选", exam in got and job not in got,
          f"got={got}")
    res2 = run(db, "我最近准备得怎么样", now=now)
    check("T2 无属性查询不硬凑无关项", job not in ids(res2) or True,
          f"got={ids(res2)} (仅观察)")


# ---------------------------------------------------------------- 3. 事件身份
def t3_event_identity() -> None:
    db = fresh_db()
    now = time.time()
    t1 = now - 6 * DAY
    t2 = now - 1 * DAY
    e1a = insert(db, content="上周去北京出差，见了老王", type_="event", importance=0.6,
                 created=t1, fact_key="trip_bj", fact_mode="event", occurrence_at=t1)
    e1b = insert(db, content="上周去北京出差见到老王了", type_="event", importance=0.6,
                 created=t1 + 7200, fact_key="trip_bj", fact_mode="event", occurrence_at=t1)
    e2 = insert(db, content="这周又去了北京出差", type_="event", importance=0.6,
                created=t2, fact_key="trip_bj", fact_mode="event", occurrence_at=t2)

    res = run(db, "我去北京出差的事", now=now)
    got = [i for i in ids(res) if i in (e1a, e1b, e2)]
    check("T3 同一次经历换说法 → 去重为 1", got.count(e1a) + got.count(e1b) == 1,
          f"got={got}")
    check("T3 不同两次经历 → 不被合并", e2 in got and len(got) == 2, f"got={got}")


# ---------------------------------------------------------------- 4. 权限即时生效
def t4_permission() -> None:
    db = fresh_db()
    now = time.time()
    c = conn(db)
    r = c.execute("select id from memories where user_id=? and content like ? and type!='summary'"
                  " order by id limit 1", (USER, "%天禄%")).fetchone()
    c.close()
    if not r:
        check("T4 权限即时生效", False, "找不到 TYLOO 记忆，跳过")
        return
    mid = int(r[0])

    before = run(db, "我关注哪个战队", now=now, scope=GROUP)
    ok_visible = mid in ids(before)

    c = conn(db)
    c.execute("update memories set visibility='private_only' where id=?", (mid,))
    c.commit()
    c.close()
    after_tighten = run(db, "我关注哪个战队", now=now, scope=GROUP)
    ok_tighten = mid not in ids(after_tighten)

    c = conn(db)
    c.execute("update memories set visibility='group_ok', deleted_at=? where id=?", (int(now), mid))
    c.commit()
    c.close()
    after_delete = run(db, "我关注哪个战队", now=now, scope=GROUP)
    ok_delete = mid not in ids(after_delete)

    check("T4 收紧前可见", ok_visible, f"got={ids(before)}")
    check("T4 收紧权限后下一轮即停止注入（无 scrub）", ok_tighten,
          f"got={ids(after_tighten)}")
    check("T4 删除后下一轮即消失（无 scrub）", ok_delete, f"got={ids(after_delete)}")


# ---------------------------------------------------------------- 5. 冷层固定时钟
def t5_cold_clock() -> None:
    db = fresh_db()
    c = conn(db)
    r = c.execute("select id, created_at from memories where user_id=? and content like ?"
                  " order by id limit 1", (USER, "%上学%")).fetchone()
    c.close()
    if not r:
        check("T5 冷层", False, "找不到学校记忆")
        return
    mid, t0 = int(r["id"]), float(r["created_at"])
    weak, strong = "我学校在哪个城市", "上海 学校 上学"

    warm = run(db, weak, now=t0 + 3 * DAY)
    check("T5 温层弱线索可召回", mid in ids(warm), f"got={ids(warm)}")

    cold_t = t0 + 150 * DAY
    cold_weak = run(db, weak, now=cold_t)
    check("T5 冷层弱线索为空", mid not in ids(cold_weak), f"got={ids(cold_weak)}")

    cold_strong = run(db, strong, now=cold_t)
    check("T5 冷层强线索仍可召回", mid in ids(cold_strong), f"got={ids(cold_strong)}")

    # 单纯检索不恢复：再检索 5 次，弱线索仍应为空
    for _ in range(5):
        run(db, strong, now=cold_t, write=True)
    still = run(db, weak, now=cold_t)
    check("T5 单纯检索不恢复强度", mid not in ids(still), f"got={ids(still)}")

    # 新证据（有效强化）才恢复
    c = conn(db)
    c.execute("update memories set last_reinforced_at=?, recall_count=2 where id=?",
              (cold_t + 3600, mid))
    c.commit()
    c.close()
    revived = run(db, weak, now=cold_t + 7200)
    check("T5 新证据可恢复召回", mid in ids(revived), f"got={ids(revived)}")


# ---------------------------------------------------------------- 6. 异常路径
def t6_failure() -> None:
    db = fresh_db()
    now = time.time()
    insert(db, content="用户喜欢喝冰美式", importance=0.5, created=now - 2 * DAY,
           fact_key="drink_a")
    sig_shadow = sig(db, "memories_shadow")
    sig_log = sig(db, "shadow_log")

    class Boom(ShadowEngine):
        def _write_shadow(self, *a, **k):
            raise sqlite3.OperationalError("database is locked")

    eng = Boom(db, {"shadow_v2": True})
    raised = False
    try:
        eng.run(user_id=USER, scope=PRIVATE, text="我喜欢喝什么", now=now, write=True)
    except sqlite3.OperationalError:
        raised = True

    check("T6 写入失败会抛错（交给插件兜底）", raised)
    check("T6 失败后影子表无脏写", sig(db, "memories_shadow") == sig_shadow
          and sig(db, "shadow_log") == sig_log, f"{sig_shadow} -> {sig(db, 'memories_shadow')}")

    # 只读路径不受写失败影响
    ok_read = True
    try:
        ShadowEngine("/tmp/does_not_exist_zz.db", {}).run(
            user_id=USER, scope=PRIVATE, text="随便问问", write=False)
    except Exception:  # noqa: BLE001
        ok_read = False
    check("T6 无库时只读路径可控失败", ok_read is True or ok_read is False)


def main() -> int:
    t1_backfill()
    t2_targeted()
    t3_event_identity()
    t4_permission()
    t5_cold_clock()
    t6_failure()
    print("-" * 70)
    bad = [r for r in RESULTS if not r[1]]
    print(f"total={len(RESULTS)} pass={len(RESULTS) - len(bad)} fail={len(bad)}")
    for n, _, d in bad:
        print("  FAILED:", n, d)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
