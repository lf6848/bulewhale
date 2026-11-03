#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""遗忘树 v2 结构迁移（幂等，可重复执行）。
只加列/加表/回填，不改任何正文，不删任何行。
用法：python3 mem_migrate_v2.py [--db PATH] [--dry]
"""
import argparse
import math
import os
import sqlite3
import sys
import time

DEFAULT_DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"

COLS = [
    # name, declare
    ("status", "TEXT NOT NULL DEFAULT 'active'"),
    ("superseded_by", "INTEGER NOT NULL DEFAULT 0"),
    ("supersedes_id", "INTEGER NOT NULL DEFAULT 0"),
    ("subject_id", "TEXT NOT NULL DEFAULT ''"),
    ("event_at", "INTEGER NOT NULL DEFAULT 0"),
    ("occurrence_at", "INTEGER NOT NULL DEFAULT 0"),
    ("valid_from", "INTEGER NOT NULL DEFAULT 0"),
    ("valid_to", "INTEGER NOT NULL DEFAULT 0"),
    ("fact_mode", "TEXT NOT NULL DEFAULT 'state'"),
    ("fact_key", "TEXT NOT NULL DEFAULT ''"),
    ("source_msg_ids", "TEXT NOT NULL DEFAULT '[]'"),
    ("content_brief", "TEXT NOT NULL DEFAULT ''"),
    ("last_reinforced_at", "INTEGER NOT NULL DEFAULT 0"),
    ("initial_strength_s", "REAL NOT NULL DEFAULT 0"),
    ("recall_count", "INTEGER NOT NULL DEFAULT 0"),
    ("pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("visibility", "TEXT NOT NULL DEFAULT 'group_ok'"),
    ("allow_groups", "TEXT NOT NULL DEFAULT '[]'"),
    ("decay_class", "TEXT NOT NULL DEFAULT 'work'"),
    ("strength_shadow", "REAL NOT NULL DEFAULT 0"),
    ("cold_shadow", "INTEGER NOT NULL DEFAULT 0"),
    ("deleted_at", "INTEGER NOT NULL DEFAULT 0"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status)",
    "CREATE INDEX IF NOT EXISTS idx_mem_reinforced ON memories(last_reinforced_at)",
    "CREATE INDEX IF NOT EXISTS idx_mem_subject ON memories(subject_id)",
    "CREATE INDEX IF NOT EXISTS idx_mem_factkey ON memories(fact_key)",
]

TABLES = [
    """CREATE TABLE IF NOT EXISTS processed_messages (
        message_id TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL DEFAULT '',
        window_id  TEXT NOT NULL DEFAULT '',
        ts         INTEGER NOT NULL DEFAULT 0,
        result     TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS reinforce_events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id     INTEGER NOT NULL,
        window_id     TEXT NOT NULL,
        source_msg_id TEXT NOT NULL DEFAULT '',
        ts            INTEGER NOT NULL DEFAULT 0,
        UNIQUE(memory_id, window_id)
    )""",
    """CREATE TABLE IF NOT EXISTS memory_events (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id INTEGER NOT NULL,
        op        TEXT NOT NULL,
        before    TEXT NOT NULL DEFAULT '{}',
        after     TEXT NOT NULL DEFAULT '{}',
        actor     TEXT NOT NULL DEFAULT 'system',
        ts        INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS memories_shadow (
        memory_id          INTEGER PRIMARY KEY,
        recall_count       INTEGER NOT NULL DEFAULT 0,
        last_reinforced_at INTEGER NOT NULL DEFAULT 0,
        status             TEXT NOT NULL DEFAULT 'active',
        superseded_by      INTEGER NOT NULL DEFAULT 0,
        strength_s         REAL NOT NULL DEFAULT 0,
        cold               INTEGER NOT NULL DEFAULT 0,
        updated_at         INTEGER NOT NULL DEFAULT 0
    )""",
]

SCHEMA_VERSION = 1


def s0_seconds(importance: float) -> float:
    days = max(2.0, 0.75 * math.exp(3.2 * float(importance)))
    return days * 86400.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print("DB not found:", args.db)
        return 2

    conn = sqlite3.connect(args.db, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")

    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    print("user_version before:", ver)

    have = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
    todo = [(n, d) for n, d in COLS if n not in have]
    print("columns to add:", [n for n, _ in todo] or "(none)")

    if args.dry:
        print("dry run, nothing written")
        return 0

    conn.execute("BEGIN IMMEDIATE")
    try:
        for name, decl in todo:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {name} {decl}")
        for sql in INDEXES + TABLES:
            conn.execute(sql)

        total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        # 回填：last_reinforced_at 一律用 created_at（不混用 event_at）
        cur = conn.execute(
            "SELECT id, importance, created_at, type, user_id, "
            "last_reinforced_at, initial_strength_s FROM memories"
        )
        rows = cur.fetchall()
        filled = 0
        for r in rows:
            rid = r["id"]
            created = int(r["created_at"] or 0)
            upd = {}
            if not r["last_reinforced_at"]:
                upd["last_reinforced_at"] = created
            if not r["initial_strength_s"]:
                upd["initial_strength_s"] = s0_seconds(r["importance"] or 0.5)
            upd["subject_id"] = "" if r["type"] == "summary" else (r["user_id"] or "")
            upd["owner_id"] = r["user_id"] or ""
            upd["fact_mode"] = "event" if r["type"] == "event" else "state"
            if upd:
                sets = ", ".join(f"{k}=?" for k in upd)
                conn.execute(f"UPDATE memories SET {sets} WHERE id=?", (*upd.values(), rid))
                filled += 1
        print("rows backfilled:", filled, "of", total)

        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except Exception as exc:  # noqa: BLE001
        conn.execute("ROLLBACK")
        print("MIGRATION FAILED:", exc)
        return 1

    chk = conn.execute("PRAGMA integrity_check").fetchone()[0]
    stats = {
        "rows": conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
        "no_reinforced": conn.execute("SELECT COUNT(*) FROM memories WHERE last_reinforced_at=0").fetchone()[0],
        "no_strength": conn.execute("SELECT COUNT(*) FROM memories WHERE initial_strength_s=0").fetchone()[0],
        "status": dict(conn.execute("SELECT status, COUNT(*) FROM memories GROUP BY status").fetchall()),
        "visibility": dict(conn.execute("SELECT visibility, COUNT(*) FROM memories GROUP BY visibility").fetchall()),
        "fact_mode": dict(conn.execute("SELECT fact_mode, COUNT(*) FROM memories GROUP BY fact_mode").fetchall()),
        "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "integrity": chk,
        "new_tables": [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('processed_messages','reinforce_events','memory_events','memories_shadow')")],
    }
    for k, v in stats.items():
        print(f"{k}: {v}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
