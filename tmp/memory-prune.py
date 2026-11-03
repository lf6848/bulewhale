#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AstrBot 长期记忆库：按「库文件体积」定期巡检，到线自动删减。

策略（用户 2026-10-26 定：到 90MB 才删）：
  - 库体积 < MAX_MB(90)      → 只报告，不动数据
  - 库体积 >= MAX_MB         → 按价值从低到高删，直到预估体积 <= TARGET_MB(70)
  - 删完执行 VACUUM 回收磁盘（WAL 模式，带 busy_timeout 重试）

永不删：
  1. type in (user_fact, preference, relationship) 且 importance >= 0.6 的画像记忆
  2. 每个用户最近 KEEP_SUMMARIES 条 summary
删除顺序：其余按 (importance asc, created_at asc)，即最不重要、最旧的先走。

用法：
  memory-prune.py                      # DRY-RUN，只报告
  memory-prune.py --apply              # 达到 90MB 才真删
  memory-prune.py --apply --max-mb 90 --target-mb 70
  memory-prune.py --no-notify
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.request
from datetime import datetime

DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
ONEBOT_HTTP = "http://127.0.0.1:3000"
ONEBOT_TOKEN = os.environ.get("ONEBOT_TOKEN", "")
OWNER_QQ = "1034867860"

MAX_MB = 90.0        # 达到这个体积才执行删减
TARGET_MB = 70.0     # 删到这个体积以下
WARN_MB = 70.0       # 到这个体积先发一条预警（不删）
PROTECT_IMPORTANCE = 0.6
KEEP_SUMMARIES = 3
PROTECT_TYPES = ("user_fact", "preference", "relationship")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def send_qq(text):
    if not ONEBOT_TOKEN:
        log("ONEBOT_TOKEN 未配置，跳过 QQ 提醒")
        return False
    payload = json.dumps({"user_id": OWNER_QQ, "message": text}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        ONEBOT_HTTP + "/send_private_msg",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + ONEBOT_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:  # noqa: BLE001
        log(f"QQ 提醒发送失败: {e}")
        return False


def db_bytes(conn, path):
    ps = conn.execute("PRAGMA page_size").fetchone()[0]
    pc = conn.execute("PRAGMA page_count").fetchone()[0]
    size = ps * pc
    wal = path + "-wal"
    if os.path.exists(wal):
        size += os.path.getsize(wal)
    return size


def pick_deletions(rows, n):
    """从某个用户的全部记忆里挑 n 条最该删的。"""
    protected = {
        r["id"] for r in rows
        if r["type"] in PROTECT_TYPES and float(r["importance"]) >= PROTECT_IMPORTANCE
    }
    summaries = sorted(
        (r for r in rows if r["type"] == "summary"),
        key=lambda r: r["created_at"], reverse=True,
    )
    protected |= {r["id"] for r in summaries[:KEEP_SUMMARIES]}

    pool = [r for r in rows if r["id"] not in protected]
    pool.sort(key=lambda r: (float(r["importance"]), r["created_at"]))
    return pool[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="达到上限时真正删除")
    ap.add_argument("--max-mb", type=float, default=MAX_MB)
    ap.add_argument("--target-mb", type=float, default=TARGET_MB)
    ap.add_argument("--warn-mb", type=float, default=WARN_MB)
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--cap", type=int, default=0, help="按条数上限兜底（0=关闭）")
    ap.add_argument("--db", default=DB, help="数据库路径（默认生产库）")
    args = ap.parse_args()

    dbpath = args.db
    if not os.path.exists(dbpath):
        log(f"DB 不存在: {dbpath}")
        return 0

    conn = sqlite3.connect(dbpath, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")

    total = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
    size = db_bytes(conn, dbpath)
    size_mb = size / 1024 / 1024
    per_user = conn.execute(
        "SELECT user_id, count(*) c FROM memories GROUP BY user_id ORDER BY c DESC"
    ).fetchall()

    log(f"模式={'APPLY' if args.apply else 'DRY-RUN'} 总体积={size_mb:.1f}MB 总记忆={total} 条 "
        f"用户数={len(per_user)} 阈值={args.max_mb:.0f}MB→{args.target_mb:.0f}MB")
    for u in per_user:
        log(f"  user={u['user_id']} 条数={u['c']}")

    need = 0
    if size_mb >= args.max_mb:
        avg = max(1.0, size / max(1, total))
        need = int(math.ceil((size - args.target_mb * 1024 * 1024) / avg))
        log(f"体积已达 {size_mb:.1f}MB ≥ {args.max_mb:.0f}MB，平均 {avg:.0f} 字节/条，需删约 {need} 条")
    elif size_mb >= args.warn_mb:
        log(f"体积 {size_mb:.1f}MB 已达预警线 {args.warn_mb:.0f}MB（未到 {args.max_mb:.0f}MB，暂不删）")

    deleted = 0
    if need > 0:
        # 按条数占比分摊到各用户，避免只删活跃用户
        allocations = []
        remaining = need
        for i, u in enumerate(per_user):
            share = int(round(need * u["c"] / total)) if total else 0
            allocations.append([u["user_id"], min(share, u["c"]), u["c"]])
        got = sum(a[1] for a in allocations)
        allocations.sort(key=lambda a: a[2], reverse=True)
        idx = 0
        while got < remaining and allocations:
            a = allocations[idx % len(allocations)]
            if a[1] < a[2]:
                a[1] += 1
                got += 1
            idx += 1
            if idx > remaining * 10:
                break

        to_delete = []
        for uid, n, _cnt in allocations:
            if n <= 0:
                continue
            rows = conn.execute(
                "SELECT id, type, importance, created_at, content FROM memories WHERE user_id = ?",
                (uid,),
            ).fetchall()
            picks = pick_deletions(rows, n)
            log(f"  user={uid} 计划删除 {len(picks)} / {len(rows)} 条")
            for r in picks[:3]:
                log(f"    - id={r['id']} type={r['type']} imp={float(r['importance']):.2f} "
                    f"{(r['content'] or '')[:36]}")
            to_delete.extend(picks)

        if args.apply and to_delete:
            conn.executemany("DELETE FROM memories WHERE id = ?", [(r["id"],) for r in to_delete])
            conn.commit()
            deleted = len(to_delete)
            log(f"已删除 {deleted} 条，准备 VACUUM 回收空间")
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.isolation_level = None
                conn.execute("VACUUM")
                log("VACUUM 完成")
            except sqlite3.Error as e:  # noqa: BLE001
                log(f"VACUUM 失败（下次巡检重试）: {e}")
        else:
            deleted = len(to_delete)
            log(f"[DRY-RUN] 将删除 {deleted} 条，未执行")

    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    conn.close()
    on_disk = os.path.getsize(dbpath)
    wal_path = dbpath + "-wal"
    if os.path.exists(wal_path):
        on_disk += os.path.getsize(wal_path)
    after_mb = on_disk / 1024 / 1024
    log(f"结束：体积 {size_mb:.1f}MB → {after_mb:.1f}MB，删除 {deleted} 条"
        f"（{'已提交' if args.apply and deleted else '仅报告'}）")

    if not args.no_notify:
        if size_mb >= args.max_mb:
            msg = (
                f"【记忆库已到 {args.max_mb:.0f}MB】\n"
                f"体积 {size_mb:.1f}MB，共 {total} 条\n"
                + ("已删除 %d 条，现 %.1fMB" % (deleted, after_mb) if args.apply and deleted
                   else "待删 %d 条（当前为只报告模式，未删除）" % deleted)
            )
            ok = send_qq(msg)
            log(f"QQ 提醒: {'已发送' if ok else '发送失败'}")
        elif size_mb >= args.warn_mb:
            ok = send_qq(f"【记忆库预警】体积 {size_mb:.1f}MB / {total} 条，"
                         f"到 {args.max_mb:.0f}MB 会自动清理")
            log(f"QQ 预警: {'已发送' if ok else '发送失败'}")
        else:
            log("体积正常，未达提醒线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
