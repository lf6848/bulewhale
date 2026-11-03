# -*- coding: utf-8 -*-
"""遗忘树 v2 影子引擎（纯 Python，无 AstrBot 依赖）。

约束（与设计 v4/v5 对齐）：
- 只读 memories 表；写入只落在 memories_shadow / shadow_log。
- read_path_v2=false 时不参与任何注入。
- 定向查询对主语/属性明确不符的候选**直接排除**，不是降分。
- 事件按「同一次经历」去重；同 key 不同 occurrence 视为两次经历。
- 删除/权限收紧在装配时生效（tombstone + visibility 检查），不等 scrub。
- 状态区间用 [valid_from, valid_to)。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from typing import Any

DAY = 86400.0

DEFAULTS: dict[str, Any] = {
    "shadow_v2": True,
    "read_path_v2": False,
    "write_path_v2": False,
    "maintain_v2": False,
    "s0_base_days": 0.75,
    "s0_k": 3.2,
    "s0_floor_days": 2.0,
    "reinforce_a": 1.2,
    "h_max_days": 120.0,
    "cold_r": 0.08,
    "cold_rel_gate": 0.20,
    "rel_floor": 0.05,
    "cand_a": 24,
    "cand_b": 8,
    "cand_c": 8,
    "max_inject": 5,
    "budget_tokens": 320,
    "chars_per_token": 1.6,
    "keep_ratio": 0.70,
    "inject_user_ids": [],
    "inject_max_chars": 400,
}

CJK = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD = re.compile(r"[a-zA-Z0-9_]{2,}")
STOP = set("的了是我你他她它在有和就不都也这那吗呢吧啊很还个上说要去会着看好自己没把被给对让")

# 属性词表：用于定向查询的「属性匹配」判断
ATTR_TAGS: dict[str, list[str]] = {
    "residence": ["住", "搬", "城市", "老家", "闵行", "徐汇", "浦东", "上海", "北京", "区"],
    "school": ["上学", "学校", "校区", "大学", "念书", "读书", "专业", "毕业"],
    "pet": ["养", "宠物", "小鸡", "鸡", "猫", "狗", "喂", "仓鼠", "兔子"],
    "team": ["战队", "比赛", "天禄", "tyloo", "cs", "看比赛"],
    "sleep": ["作息", "睡", "熬夜", "几点睡"],
    "work": ["工作", "上班", "职业", "公司", "招聘", "简历", "面试", "求职", "就业", "实习"],
    "name": ["名字", "外号", "昵称", "叫我", "称呼", "名为"],
    "project": ["项目", "研发", "开发"],
    "exam": ["考研", "考试", "高考", "期末", "复习"],
    "plan": ["计划", "打算", "安排"],
    "activity": ["参加", "活动", "去了"],
    "food": ["吃", "喝", "香菜", "面", "饭"],
    "game": ["csgo", "游戏", "玩"],
}

BROAD_MARKERS = ["哪些", "都记得", "所有", "一切", "发生过", "发生了什么", "聊聊", "说说", "关于我", "你记得我"]


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _tokens(text: str) -> set[str]:
    t = _norm(text)
    out: set[str] = set()
    for w in ASCII_WORD.findall(t):
        out.add(w)
    chars = [c for c in t if CJK.match(c)]
    for c in chars:
        out.add(c)
    for a, b in zip(chars, chars[1:]):
        bg = a + b
        if not (a in STOP and b in STOP):
            out.add(bg)
    return {x for x in out if x and x not in STOP}


def _attrs(text: str) -> set[str]:
    t = _norm(text)
    hits = set()
    for tag, words in ATTR_TAGS.items():
        for w in words:
            if w in t:
                hits.add(tag)
                break
    return hits


def classify(query: str) -> tuple[str, set[str]]:
    q = _norm(query)
    broad = any(m in q for m in BROAD_MARKERS)
    attrs = _attrs(q)
    if broad:
        return "broad", attrs
    if attrs:
        return "targeted", attrs
    return "targeted", attrs


def tokenize_len(text: str, chars_per_token: float) -> int:
    return int(math.ceil(len(text or "") / max(1.0, chars_per_token)))


class ShadowEngine:
    def __init__(self, db_path: str, cfg: dict[str, Any] | None = None):
        self.db = db_path
        self.cfg = dict(DEFAULTS)
        if cfg:
            self.cfg.update({k: v for k, v in cfg.items() if k in DEFAULTS})
        self._conn: sqlite3.Connection | None = None
        # 插件里 run() 跑在线程池中，同一连接会被不同线程使用
        self._lock = threading.RLock()

    # ---------- 连接 ----------
    def _db(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                c = sqlite3.connect(self.db, timeout=10, check_same_thread=False)
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA busy_timeout=10000")
                c.execute("CREATE TABLE IF NOT EXISTS shadow_log ("
                          "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, umo TEXT, user_id TEXT,"
                          "text TEXT, mode TEXT, n_candidates INTEGER, n_injected INTEGER,"
                          "injected_ids TEXT, tokens INTEGER, notes TEXT)")
                self._conn = c
            return self._conn

    # ---------- 状态计算 ----------
    def s0_seconds(self, importance: float) -> float:
        base = max(self.cfg["s0_floor_days"],
                   self.cfg["s0_base_days"] * math.exp(self.cfg["s0_k"] * float(importance)))
        return base * DAY

    def strength(self, row: dict[str, Any]) -> float:
        s0 = float(row.get("initial_strength_s") or 0) or self.s0_seconds(row.get("importance") or 0.5)
        n = int(row.get("recall_count") or 0)
        s = s0 * (1.0 + self.cfg["reinforce_a"] * math.log(1.0 + max(0, n)))
        return min(self.cfg["h_max_days"] * DAY / math.log(2.0), s)

    def reinforce_ts(self, row: dict[str, Any]) -> float:
        ts = float(row.get("last_reinforced_at") or 0)
        if ts > 0:
            return ts
        return float(row.get("created_at") or 0)

    def recency(self, row: dict[str, Any], now: float) -> float:
        age = max(0.0, now - self.reinforce_ts(row))
        return math.exp(-age / max(1.0, self.strength(row)))

    def is_cold(self, row: dict[str, Any], now: float) -> bool:
        return (self.recency(row, now) < self.cfg["cold_r"]
                and (row.get("status") or "active") == "active"
                and not int(row.get("pinned") or 0))

    # ---------- 权限 ----------
    def _scope_kind(self, scope: str) -> tuple[str, str]:
        s = scope or ""
        if "FriendMessage" in s:
            return "private", s
        if "GroupMessage" in s:
            gid = s.rsplit(":", 1)[-1]
            return "group", gid
        return "other", s

    def permitted(self, row: dict[str, Any], scope: str, user_id: str) -> bool:
        if int(row.get("deleted_at") or 0) > 0:
            return False
        vis = (row.get("visibility") or "group_ok").strip()
        kind, sid = self._scope_kind(scope)
        owner = (row.get("owner_id") or row.get("user_id") or "").strip()
        if vis == "owner_only":
            return kind == "private" and owner == user_id
        if vis == "private_only":
            if kind != "private":
                return False
            return owner == user_id or (row.get("subject_id") or "") == user_id
        # group_ok
        try:
            groups = json.loads(row.get("allow_groups") or "[]")
        except Exception:
            groups = []
        if not groups:
            return True
        return kind == "group" and sid in {str(g) for g in groups}

    # ---------- 取数 ----------
    def load(self, user_id: str) -> list[dict[str, Any]]:
        conn = self._db()
        rows = conn.execute(
            "SELECT id, user_id, owner_id, subject_id, session_id, content, content_brief, type, tags,"
            " importance, created_at, event_at, occurrence_at, valid_from, valid_to, fact_mode, fact_key,"
            " status, superseded_by, pinned, visibility, allow_groups, deleted_at,"
            " last_reinforced_at, initial_strength_s, recall_count"
            " FROM memories WHERE user_id = ? OR subject_id = ?",
            (user_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 检索 ----------
    def run(self, *, user_id: str, scope: str, text: str, umo: str = "", now: float | None = None,
            write: bool = True) -> dict[str, Any]:
        # 线程池里可能并发进来，串行化对同一连接的访问
        with self._lock:
            return self._run(user_id=user_id, scope=scope, text=text, umo=umo, now=now, write=write)

    def _run(self, *, user_id: str, scope: str, text: str, umo: str = "", now: float | None = None,
             write: bool = True) -> dict[str, Any]:
        now = float(now or time.time())
        cfg = self.cfg
        mode, q_attrs = classify(text)
        q_tokens = _tokens(text)
        self_ask = ("我" in text) or ("我的" in text)

        rows = self.load(user_id)
        # 迁移后旧写入器新增的行：影子侧就地补算，不写生产列。
        # 注意：这是「每次请求的兜底次数」，不是「新增记忆数」；同一批记录会被反复兜底。
        fix_ids: list[int] = []
        fix_missing_ts = 0
        fix_missing_s0 = 0
        for r in rows:
            miss_ts = not r.get("last_reinforced_at")
            miss_s0 = not r.get("initial_strength_s")
            if miss_ts or miss_s0:
                fix_ids.append(int(r["id"]))
                fix_missing_ts += 1 if miss_ts else 0
                fix_missing_s0 += 1 if miss_s0 else 0

        notes: list[str] = []
        if fix_ids:
            uniq = sorted(set(fix_ids))
            notes.append(f"bf_calls={len(fix_ids)} bf_ids={len(uniq)}"
                         f" bf_missing_ts={fix_missing_ts} bf_missing_s0={fix_missing_s0}"
                         f" bf_sample={','.join(str(i) for i in uniq[:5])}")
            # 兜底时间基准固定用 created_at（见 reinforce_ts），查询本身不会把记忆变年轻
            young = [int(r["id"]) for r in rows
                     if not r.get("last_reinforced_at")
                     and float(self.reinforce_ts(r)) > float(r.get("created_at") or 0) + 1]
            if young:
                notes.append(f"bf_rejuve={len(young)}")

        cand: list[dict[str, Any]] = []
        for r in rows:
            if not self.permitted(r, scope, user_id):
                continue
            if int(r.get("deleted_at") or 0) > 0:
                continue
            vt = int(r.get("valid_to") or 0)
            if vt and vt <= now:
                continue  # [valid_from, valid_to) 已结束
            st = (r.get("status") or "active")
            if st in ("superseded", "uncertain"):
                continue
            if (r.get("type") or "") == "summary":
                continue  # 本步先隔离 summary
            mem_attrs = _attrs(r.get("content") or "")
            subj_hit = bool(r.get("subject_id")) and (r.get("subject_id") == user_id)

            # 定向查询：主语/属性明确不符 -> 直接排除
            if mode == "targeted":
                if self_ask and r.get("subject_id") and r.get("subject_id") != user_id:
                    continue
                if q_attrs and not (q_attrs & mem_attrs):
                    continue

            c_tokens = _tokens(r.get("content") or "")
            matched = q_tokens & c_tokens
            # 只有「实词」命中才算证据：CJK 二元组或 ASCII 词，单字不算
            info_hit = any(len(t) >= 2 for t in matched)
            overlap = len(matched) / max(1, len(q_tokens))
            substr = 1.0 if any(t in _norm(r.get("content") or "") for t in q_tokens if len(t) >= 2) else 0.0
            sim = 0.7 * overlap + 0.3 * substr
            attr_match = 1.0 if (q_attrs & mem_attrs) else 0.0
            # 既没有属性匹配、也没有实词命中 -> 不作为证据注入（避免"无答案题硬塞"）
            if mode == "targeted" and not attr_match and not info_hit:
                continue
            if mode == "targeted":
                rel = 0.6 * sim + 0.4 * attr_match
                if subj_hit:
                    rel = min(1.0, rel + 0.10)
            else:
                rel = max(sim, 0.85 if subj_hit else 0.0, 0.0)
            cold = self.is_cold(r, now)
            if rel < cfg["rel_floor"]:
                continue
            # 冷层：必须靠实词证据（或 pinned）叫醒，只有属性擦边不算
            if cold and not (int(r.get("pinned") or 0) or info_hit):
                continue
            if cold and rel < cfg["cold_rel_gate"]:
                continue
            r["_rel"] = rel
            r["_cold"] = cold
            r["_attrs"] = mem_attrs
            cand.append(r)

        # 冗余去除：同 fact_key 且（事件看同一次经历）才算重复
        def ident(r: dict[str, Any]) -> str:
            base = r.get("fact_key") or hashlib.sha1((r.get("content") or "").encode()).hexdigest()[:16]
            if (r.get("fact_mode") or "state") == "event":
                occ = int(r.get("occurrence_at") or r.get("event_at") or r.get("created_at") or 0) // 3600
                return f"E|{base}|{occ}"
            return f"S|{base}"

        best: dict[str, dict[str, Any]] = {}
        for r in cand:
            r["_score"] = r["_rel"] * (0.45 + 0.35 * float(r.get("importance") or 0.5)
                                       + 0.20 * self.recency(r, now))
            k = ident(r)
            cur = best.get(k)
            if cur is None or r["_score"] > cur["_score"]:
                best[k] = r
        ranked = sorted(best.values(), key=lambda x: (-x["_score"], int(x["id"])))

        injected: list[dict[str, Any]] = []
        used = 0
        top_score = ranked[0]["_score"] if ranked else 0.0
        for r in ranked:
            if len(injected) >= cfg["max_inject"]:
                break
            # 定向查询：与最佳候选差距过大的（只是属性擦边）不塞进来
            if mode == "targeted" and top_score > 0 and r["_score"] < top_score * cfg["keep_ratio"]:
                continue
            txt = (r.get("content_brief") or r.get("content") or "").strip()
            cost = tokenize_len(txt, cfg["chars_per_token"]) + 8
            if used + cost > cfg["budget_tokens"]:
                continue
            used += cost
            injected.append(r)

        # 关联回忆：想起一件事时，顺带想起与它共享属性或罕见实词的其它记忆
        # （模拟"熬夜看比赛"带出"关注天禄"；共享高频词如「用户」不算关联证据）
        if mode == "targeted" and injected and cfg.get("hop_enable", False):
            picked = {int(r["id"]) for r in injected}
            attr_union: set[str] = set()
            seed_tokens: set[str] = set()
            for r in injected:
                attr_union |= set(r.get("_attrs") or ())
                seed_tokens |= {t for t in _tokens(r.get("content") or "") if len(t) >= 2}
            df: dict[str, int] = {}
            for rr in rows:
                for t in {t for t in _tokens(rr.get("content") or "") if len(t) >= 2}:
                    df[t] = df.get(t, 0) + 1
            common = {t for t, c in df.items() if c >= max(2, len(rows) * 0.5)}
            seed_tokens -= common
            hop: list[tuple[int, dict[str, Any]]] = []
            seen_hop: set[int] = set()
            for r in cand:
                rid = int(r["id"])
                if rid in picked or rid in seen_hop:
                    continue
                share_attr = attr_union & set(r.get("_attrs") or ())
                share_tok = seed_tokens & {t for t in _tokens(r.get("content") or "") if len(t) >= 2}
                if not share_attr and not share_tok:
                    continue
                if self.is_cold(r, now) and not int(r.get("pinned") or 0):
                    continue
                seen_hop.add(rid)
                hop.append((2 * len(share_attr) + len(share_tok), r))
            hop.sort(key=lambda x: (-x[0], -float(x[1].get("importance") or 0.5), -self.recency(x[1], now)))
            hop_used = 0
            for _w, r in hop:
                if len(injected) >= cfg["max_inject"] or hop_used >= int(cfg.get("hop_max", 2)):
                    break
                txt = (r.get("content_brief") or r.get("content") or "").strip()
                cost = tokenize_len(txt, cfg["chars_per_token"]) + 8
                if used + cost > cfg["budget_tokens"]:
                    continue
                used += cost
                r["_rel"] = max(float(r.get("_rel") or 0.0), 0.25)
                r["_score"] = max(float(r.get("_score") or 0.0), 0.30)
                injected.append(r)
                hop_used += 1
            if hop_used:
                notes.append(f"hop={hop_used}")

        if write:
            self._write_shadow(rows, injected, now)
            self._log(umo, user_id, text, mode, len(cand), injected, used, notes)

        return {
            "mode": mode,
            "attrs": sorted(q_attrs),
            "candidates": len(cand),
            "injected": [{"id": int(r["id"]), "score": round(r["_score"], 3),
                          "rel": round(r["_rel"], 3), "cold": bool(r["_cold"]),
                          "content": (r.get("content") or "")[:60]} for r in injected],
            "tokens": used,
            "notes": notes,
        }

    # ---------- 影子写入 ----------
    def _write_shadow(self, rows: list[dict[str, Any]], injected: list[dict[str, Any]], now: float) -> None:
        conn = self._db()
        for r in rows:
            st = (r.get("status") or "active")
            s = self.strength(r)
            cold = 1 if self.is_cold(r, now) else 0
            conn.execute(
                "INSERT INTO memories_shadow (memory_id, recall_count, last_reinforced_at, status,"
                " superseded_by, strength_s, cold, updated_at) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(memory_id) DO UPDATE SET recall_count=excluded.recall_count,"
                " last_reinforced_at=excluded.last_reinforced_at, status=excluded.status,"
                " superseded_by=excluded.superseded_by, strength_s=excluded.strength_s,"
                " cold=excluded.cold, updated_at=excluded.updated_at",
                (int(r["id"]), int(r.get("recall_count") or 0), int(self.reinforce_ts(r)), st,
                 int(r.get("superseded_by") or 0), s, cold, int(now)))
        conn.commit()

    def _log(self, umo: str, user_id: str, text: str, mode: str, n_cand: int,
             injected: list[dict[str, Any]], tokens: int, notes: list[str]) -> None:
        conn = self._db()
        conn.execute(
            "INSERT INTO shadow_log (ts, umo, user_id, text, mode, n_candidates, n_injected,"
            " injected_ids, tokens, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (int(time.time()), umo, user_id, (text or "")[:200], mode, n_cand, len(injected),
             json.dumps([int(r["id"]) for r in injected]), tokens, ";".join(notes)))
        conn.commit()
