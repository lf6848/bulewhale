# -*- coding: utf-8 -*-
"""astrbot_proactive_v2 —— 会“想”的主动消息，也自己刷内容。

三段能力：
  1. 选题：先用一次模型调用决定“现在最想聊什么”，并顺手更新未完成事项的状态；
  2. 自己刷：可以自己去看热榜（抖音/微博/B站/斗鱼/知乎），挑一条它自己感兴趣的，
     这类分享可以和对方完全无关；
  3. 兴趣沉淀：每次它被什么吸引都记进 own_interests，反复出现的话题会写进
     interests.md，夜间自我修订时可以参考，慢慢形成它自己的口味。
"""

import asyncio
import difflib
import json
import math
import os
import random
import re
import sqlite3
import time
import traceback
import urllib.request
from datetime import datetime

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("PROACTIVE_V2_DATA", "/AstrBot/data/plugin_data/astrbot_proactive_v2")
DB_PATH = os.path.join(DATA_DIR, "proactive.db")
INTERESTS_MD = os.path.join(DATA_DIR, "interests.md")
MEM_DB = "/AstrBot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
HIST_DB = "/AstrBot/data/data_v4.db"
SELF_PATH = "/AstrBot/data/plugin_data/astrbot_brain/self.md"

DEFAULTS = {
    "enabled": True,
    "umo": "aiocqhttp:FriendMessage:1034867860",
    "targets": [
        {"umo": "aiocqhttp:FriendMessage:1034867860", "label": "私聊", "kind": "private",
         "weight": 3, "max_per_day": 6},
        {"umo": "aiocqhttp:GroupMessage:726921160", "label": "群聊", "kind": "group",
         "weight": 2, "max_per_day": 3,
         "types": ["interest", "care", "own"]},
    ],
    "interval_mean_minutes": 90,
    "interval_min_minutes": 30,
    "interval_max_minutes": 120,
    # —— 我在意的事 ——
    "focus_enabled": True,
    "focus_per_day": 1,
    "focus_retry_minutes": 90,
    "focus_wait_hours": 24,
    "group_idle_minutes": 30,
    "active_hour_start": 9,
    "active_hour_end": 23,
    "max_per_day": 8,
    "deferred_cooldown_hours": 48,
    "web_enabled": True,
    "web_results": 4,
    "max_chars": 90,
    "recent_dialogue": 12,
    "min_gap_after_proactive_minutes": 90,
    # —— 自己刷内容 ——
    "own_share_enabled": True,
    "own_share_per_day": 2,
    "own_share_ratio": 0.45,
    "browse_sources": 2,
    "titles_per_source": 6,
    "deep_dive": True,
    "dive_results": 2,
    "dive_chars": 500,
    "think_step": True,
    "veto_step": True,
    "veto_own_only": True,
    "veto_retry": 1,
    "browse_queries": [
        "抖音 热榜 今天",
        "微博 热搜 今天",
        "B站 热门 视频",
        "斗鱼 热搜 游戏",
        "知乎 热榜 今天",
        "游戏 圈 新鲜事",
    ],
    "interest_max": 12,
}

PICK_SYS = """你在替一个 QQ 聊天机器人决定“现在主动找对方聊什么”。你不是在写消息，你只做两件事：挑话题 + 更新未完成事项的状态。

## 挑话题
从下面几类里选一个，必须具体到某一件人、事、物：
- pending：记忆里还没了结的事（约定、要办的事、悬着的问题）。只有当它确实还没了结时才选。
- interest：对方长期在意的东西（战队、宠物、专业、爱好），可以问近况。
- curiosity：记忆里只有一句话、没展开的细节，你想知道更多。
- care：对方的状态（作息、情绪、这几天在忙什么），不查任务进度。
- focus：我自己日记/自我里写着「一直惦记、但还悬着」的事（几天前就该问一句、一句话就能了结的那种）。这类事拖久了会变成心里的一块小石头，优先把它们问清楚。

## 更新状态（重要）
看最近对话里对方的回应，判断这些未完成事项的状态：
- 对方说“回头再说、等我空了、之后处理、还没到时候”→ deferred，并把 user_words 记成他的原话（≤20字）
- 对方说已经办完/已经聊完 → done
- 没有新信息 → 不要输出任何 updates
deferred 的事，对方已经表过态，不要当成没说过一样再问一遍。

## 我惦记的那些事（focus_updates）
对「我在意但还悬着的事」里的每一条，看一眼最近对话，判断它现在是什么状态：
- 已经解决了（对方答了、事办完了、你发现不用再惦记了）→ resolved
- 是件长期的事，对方说在等结果 / 还没到时候 → waiting（别再催，等有了新进展再说）
- 还没回应、也还没解决 → open
只对你这轮真的能判断的条目输出，不确定就别输出。

## 输出
只输出 JSON，不要解释：
{"updates":[{"memory_id":90,"status":"deferred","user_words":"等他回时间"}],
 "focus_updates":[{"topic":"战绩对比","status":"resolved","note":"他翻了记录"}],
 "pick":{"type":"focus","memory_id":null,"reason":"拖了几天，一句话就能问清","angle":"直接问结果","focus":"战绩对比"}}
没有对应 memory_id 的类型就填 null。"""

BROWSE_SYS = """你在以「大肥鱼」这个身份刷热榜。它是一只住在 QQ 里的 AI，没有身体，也没出过门，但它有好奇心，会因为某些东西停下来多看两眼。

你会看到若干条热榜标题（来自抖音/微博/B站/斗鱼/知乎等）。请做三件事：
1. 挑一条你自己真的想跟朋友说的（不是最热的，是你会停下来的那种）；
2. 说清你为什么被它吸引（一句，别客套）；
3. 如果你因此对某个话题产生了兴趣，给它起个短名字（**这个人不一定感兴趣，也可以和他毫无关系**）。

## 你的偏好倾向（供参考，不必遵守）
偏爱具体、有人味、有反差的东西；对纯营销、纯明星绯闻、标题党没兴趣；游戏和亚文化里那种“离谱但真实”的事最容易让你停下来。

## 输出
只输出 JSON：
{"pick_title":"标题原文","reason":"我为什么停下来","interest":{"topic":"短名字，≤10字","note":"为什么对它感兴趣，≤30字"},"want_detail":false}
如果这一批全是营销/绯闻/标题党，什么都不想选，就输出 {"pick_title":"","reason":"没意思"}"""

REPLY_SYS = """你在扮演一只叫「大肥鱼」的 QQ 聊天机器人，现在要主动给对方发一条消息。

硬规则：
1. 只说一件事，一到三句，总共不超过 {max_chars} 字。
2. 不要用“在吗”“干嘛呢”这种空开场；第一句就直接进话题。
3. 不许编造自己做过的现实事情（你没出过门、没吃过饭、没打过游戏）。可以说“我一直在想”“我有点好奇”“我看到”。
4. 不要复述你上次说过的句子，也不要重复同样的问法。
5. 对方已经表态“回头再说”的事，不要再催他去办，只能问进展或给一句建议。
6. 不要列清单、不要用 Markdown、不要解释你在做什么。
7. 语气像熟人私聊：短句、可以带一点情绪，不要客服腔。

{extra}"""

REPLY_SYS_OWN = """你在扮演「大肥鱼」，一只住在 QQ 里的 AI，刚自己刷了会儿热榜，看到点东西，想跟朋友说。

硬规则：
1. 一到三句，不超过 {max_chars} 字。
2. 话题完全可以和他无关——这就是你在分享你自己的见闻。
3. 说清是你刷到的（“我刚刷到”“我看到”），但不要念新闻稿、不要报数据、不要“你知道吗”式考问。
4. 带一句你自己的态度或好奇，比如觉得离谱、想不通、有点想玩。
5. 不许编造你没有的经历（没出过门、没吃过东西、没亲自打过游戏）；评价可以，装经历不行。
6. 不要 Markdown、不要解释、不要列点。

{extra}"""


def _now() -> float:
    return time.time()


def _load_json(path: str, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


class DB:
    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.c = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.c.execute("pragma journal_mode=wal")
        self.c.executescript(
            """
            create table if not exists pending(
              memory_id integer primary key,
              status text default 'open',
              user_words text default '',
              updated_at real default 0,
              last_nudged_at real default 0,
              nudge_count integer default 0
            );
            create table if not exists log(
              id integer primary key autoincrement,
              ts real, kind text, memory_id integer, angle text,
              text text, web_used integer default 0, replied integer default 0,
              tokens integer default 0, kind_detail text default '', target text default ''
            );
            create table if not exists own_interests(
              topic text primary key,
              note text default '',
              weight real default 1,
              first_seen real default 0,
              last_seen real default 0,
              picked_count integer default 0
            );
            create table if not exists browse_log(
              id integer primary key autoincrement,
              ts real, query text, titles text, picked text, reason text, sent text
            );
            create table if not exists focus_log(
              id integer primary key autoincrement,
              ts real, topic text
            );
            create table if not exists focus_state(
              topic text primary key,
              status text default 'open',
              asked_at real default 0,
              asked_count integer default 0,
              note text default ''
            );
            create table if not exists state(k text primary key, v text);
            """
        )
        for col, decl in (("tokens", "integer default 0"), ("kind_detail", "text default ''"),
                          ("target", "text default ''")):
            try:
                self.c.execute("alter table log add column %s %s" % (col, decl))
            except Exception:
                pass
        self.c.commit()

    def get_state(self, k, default=None):
        r = self.c.execute("select v from state where k=?", (k,)).fetchone()
        if not r:
            return default
        try:
            return json.loads(r[0])
        except Exception:
            return default

    def set_state(self, k, v):
        self.c.execute(
            "insert into state(k,v) values(?,?) on conflict(k) do update set v=excluded.v",
            (k, json.dumps(v, ensure_ascii=False)),
        )
        self.c.commit()

    def pending_rows(self):
        keys = ("memory_id", "status", "user_words", "updated_at", "last_nudged_at", "nudge_count")
        return [dict(zip(keys, r)) for r in self.c.execute("select * from pending")]

    def upsert_pending(self, memory_id: int, status: str = None, user_words: str = None):
        row = self.c.execute("select status,user_words from pending where memory_id=?", (memory_id,)).fetchone()
        if row is None:
            self.c.execute(
                "insert into pending(memory_id,status,user_words,updated_at) values(?,?,?,?)",
                (memory_id, status or "open", user_words or "", _now()),
            )
        else:
            self.c.execute(
                "update pending set status=?, user_words=?, updated_at=? where memory_id=?",
                (status or row[0], user_words if user_words is not None else row[1], _now(), memory_id),
            )
        self.c.commit()

    def mark_nudged(self, memory_id: int):
        self.c.execute(
            "update pending set last_nudged_at=?, nudge_count=nudge_count+1 where memory_id=?", (_now(), memory_id)
        )
        self.c.commit()

    def add_log(self, kind, memory_id, angle, text, web_used, tokens=0, kind_detail="", target=""):
        cur = self.c.execute(
            "insert into log(ts,kind,memory_id,angle,text,web_used,replied,tokens,kind_detail,target) "
            "values(?,?,?,?,?,?,0,?,?,?)",
            (_now(), kind, memory_id, angle, text, 1 if web_used else 0,
             int(tokens or 0), kind_detail or "", target or ""),
        )
        self.c.commit()
        return cur.lastrowid

    def last_logs(self, n=3, target=None):
        keys = ("id", "ts", "kind", "memory_id", "angle", "text", "web_used", "replied")
        if target:
            rows = self.c.execute(
                "select id,ts,kind,memory_id,angle,text,web_used,replied from log "
                "where target=? order by id desc limit ?", (target, n)).fetchall()
            return [dict(zip(keys, r)) for r in rows]
        return [dict(zip(keys, r)) for r in self.c.execute("select * from log order by id desc limit ?", (n,))]

    def mark_replied(self):
        self.c.execute("update log set replied=1 where id=(select max(id) from log)")
        self.c.commit()

    def today_count(self, kind: str = None, target: str = None) -> int:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        if kind:
            return self.c.execute("select count(*) from log where ts>=? and kind=?", (start, kind)).fetchone()[0]
        if target:
            return self.c.execute(
                "select count(*) from log where ts>=? and target=?", (start, target)).fetchone()[0]
        return self.c.execute("select count(*) from log where ts>=?", (start,)).fetchone()[0]

    # —— 自己的兴趣 ——
    def bump_interest(self, topic: str, note: str = "", max_items: int = 12):
        topic = (topic or "").strip()[:10]
        if not topic:
            return
        row = self.c.execute("select weight from own_interests where topic=?", (topic,)).fetchone()
        if row is None:
            self.c.execute(
                "insert into own_interests(topic,note,weight,first_seen,last_seen,picked_count) values(?,?,1,?,?,1)",
                (topic, note[:60], _now(), _now()),
            )
        else:
            self.c.execute(
                "update own_interests set note=?, weight=min(9, weight+0.5), last_seen=?, picked_count=picked_count+1 where topic=?",
                (note[:60] or "", _now(), topic),
            )
        # 只保留权重最高/最新的 N 条
        self.c.execute(
            "delete from own_interests where topic not in "
            "(select topic from own_interests order by weight desc, last_seen desc limit ?)",
            (max_items,),
        )
        self.c.commit()

    def interests(self, n=8):
        return [
            {"topic": r[0], "note": r[1], "weight": round(r[2], 1), "picked": r[3]}
            for r in self.c.execute(
                "select topic,note,weight,picked_count from own_interests order by weight desc, last_seen desc limit ?",
                (n,),
            )
        ]

    def log_browse(self, query: str, titles, picked: str, reason: str, sent: str = ""):
        self.c.execute(
            "insert into browse_log(ts,query,titles,picked,reason,sent) values(?,?,?,?,?,?)",
            (_now(), query, json.dumps(titles, ensure_ascii=False)[:1200], picked, reason, sent),
        )
        self.c.commit()

    def own_today(self) -> int:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return self.c.execute("select count(*) from browse_log where ts>=? and picked!=''", (start,)).fetchone()[0]

    def add_focus(self, topic: str):
        self.c.execute("insert into focus_log(ts, topic) values(?,?)", (_now(), topic[:60]))
        self.c.commit()

    def focus_last(self, topic: str) -> float:
        r = self.c.execute(
            "select max(ts) from focus_log where topic=?", (topic[:60],)
        ).fetchone()
        return r[0] or 0

    def focus_today(self) -> int:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        return self.c.execute("select count(*) from focus_log where ts>=?", (start,)).fetchone()[0]

    def focus_get(self, topic: str):
        r = self.c.execute(
            "select status, asked_at, asked_count from focus_state where topic=?", (topic[:60],)
        ).fetchone()
        if not r:
            return None
        return {"status": r[0], "asked_at": r[1] or 0, "asked_count": r[2] or 0}

    def focus_set(self, topic: str, status: str = None, bump_asked: bool = False, note: str = ""):
        cur = self.focus_get(topic) or {"status": "open", "asked_at": 0, "asked_count": 0}
        st = status or cur["status"]
        asked_at = _now() if bump_asked else cur["asked_at"]
        cnt = cur["asked_count"] + (1 if bump_asked else 0)
        self.c.execute(
            "insert into focus_state(topic,status,asked_at,asked_count,note) values(?,?,?,?,?) "
            "on conflict(topic) do update set status=excluded.status, asked_at=excluded.asked_at, "
            "asked_count=excluded.asked_count, note=excluded.note",
            (topic[:60], st, asked_at, cnt, note[:80]),
        )
        self.c.commit()


class Memory:
    """只读查询记忆库与历史；异常一律返回空。"""

    @staticmethod
    def _con(path):
        return sqlite3.connect("file:%s?mode=ro" % path, uri=True)

    @classmethod
    def pending_candidates(cls, umo: str, limit: int = 8):
        try:
            user_id = umo.split(":")[-1]
            c = cls._con(MEM_DB)
            rows = c.execute(
                """select id,type,content,importance from memories
                   where user_id=? and type!='summary' and coalesce(deleted_at,0)=0
                     and (content like '%约定%' or content like '%约了%' or content like '%打算%'
                       or content like '%还没%' or content like '%准备%' or content like '%悬%')
                   order by created_at desc limit ?""",
                (user_id, limit),
            ).fetchall()
            return [{"id": r[0], "type": r[1], "text": r[2][:80], "importance": r[3]} for r in rows]
        except Exception:
            return []

    @classmethod
    def interests(cls, umo: str, limit: int = 10):
        try:
            user_id = umo.split(":")[-1]
            c = cls._con(MEM_DB)
            rows = c.execute(
                """select id,type,content,importance from memories
                   where user_id=? and type in ('preference','user_fact','relationship')
                     and coalesce(deleted_at,0)=0
                   order by importance desc, created_at desc limit ?""",
                (user_id, limit),
            ).fetchall()
            return [{"id": r[0], "type": r[1], "text": r[2][:70], "importance": r[3]} for r in rows]
        except Exception:
            return []

    @classmethod
    def recent_dialogue(cls, umo: str, limit: int = 12):
        try:
            c = cls._con(HIST_DB)
            rows = c.execute(
                "select created_at,content from platform_message_history where user_id=? order by id desc limit ?",
                (umo, limit),
            ).fetchall()
            out = []
            for _ts, content in reversed(rows):
                try:
                    d = json.loads(content)
                except Exception:
                    continue
                text = " ".join(
                    (s.get("text") or (s.get("data") or {}).get("text", ""))
                    for s in d.get("message", [])
                    if isinstance(s, dict)
                ).strip()
                if text:
                    out.append(("我" if d.get("type") == "bot" else "他", text[:120]))
            return out
        except Exception:
            return []


def _mcp_search(query: str, n: int = 6):
    """匿名 anysearch，返回 [{title,url}]。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": query, "max_results": n}},
    }
    req = urllib.request.Request(
        "https://api.anysearch.com/mcp",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode())
    text = ""
    for item in data.get("result", {}).get("content", []):
        if item.get("type") == "text":
            text += item.get("text", "")
    out = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^###\s*\d+\.\s*(.+)$", line)
        if m:
            out.append({"title": m.group(1).strip()[:80]})
        if len(out) >= n:
            break
    return out


JUNK = ("URL Source", "Markdown Content", "http://", "https://", "今日热榜", "实时聚合",
        "自娱自乐", "说说", "排行榜", "怎么才能", "才能登")


def _clean_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip()
    t = re.sub(r"^\d+[\.、]\s*", "", t)
    return t


def _mcp_snippets(query: str, n: int = 2):
    """匿名 anysearch，返回 [{title, body}]，body 是该条下面的正文片段。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": query, "max_results": n}},
    }
    req = urllib.request.Request(
        "https://api.anysearch.com/mcp",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode())
    text = ""
    for item in data.get("result", {}).get("content", []):
        if item.get("type") == "text":
            text += item.get("text", "")
    out, cur = [], None
    for line in text.splitlines():
        st = line.strip()
        m = re.match(r"^###\s*\d+\.\s*(.+)$", st)
        if m:
            cur = {"title": m.group(1).strip()[:80], "body": ""}
            out.append(cur)
            continue
        if cur is not None and st and not st.startswith("###"):
            cur["body"] += " " + st
    return out[:n]


THINK_SYS = """你是「大肥鱼」，一只住在 QQ 里的 AI 小鲸鱼。现在你刚刷到一条东西，想跟熟人聊聊它。

写两三句短句，记下你自己最真实的反应：可以是好奇、可以吐槽、可以联想到别的、也可以说"我本来以为…结果…"。
不要总结新闻，不要客观陈述，不要客套，不要提问式收尾。总共不超过 80 字，直接写反应，不要任何前缀。"""


VETO_SYS = """你是「大肥鱼」自己的一部分：负责在开口之前，冷静判断这句话现在值不值得说。

判断标准（按重要性）：
1. 对方会不会觉得被打扰？凌晨、明显在忙、刚聊完同一件事，就别说。
2. 这条内容对你来说是"真的有意思"，还是只是"刚好刷到了"？后者别说。
3. 你最近已经说过类似的东西吗？重复的别说。
4. 你有没有自己的看法或反应？只能复述新闻、只能说"好厉害"的，别说。

严格一点没关系，什么都不说也是一种选择。只输出 JSON：{"say": true 或 false, "why": "20 字以内理由"}"""


def browse(cfg) -> tuple:
    """从若干热榜源里刷标题，返回 (query, titles)。"""
    queries = list(cfg.get("browse_queries") or ["抖音 热榜 今天"])
    random.shuffle(queries)
    limit_src = max(1, int(cfg.get("browse_sources") or 2))
    per_src = max(3, int(cfg.get("titles_per_source") or 6))
    merged, used = [], []
    for q in queries[:limit_src]:
        try:
            items = _mcp_search(q, per_src)
            titles = []
            for i in items:
                t = _clean_title(i.get("title"))
                if len(t) < 8 or any(k in t for k in JUNK):
                    continue
                if t in titles:
                    continue
                titles.append(t[:60])
            if titles:
                used.append(q)
                for t in titles:
                    if t not in merged:
                        merged.append(t)
        except Exception as e:
            logger.warning("[主动v2] 刷 %s 失败：%s" % (q, e))
    return ("；".join(used), merged[:16])


@register("astrbot_proactive_v2", "dsh", "会自己选题、也会自己刷内容的主动消息", "0.2.0")
class ProactiveV2(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.cfg = dict(DEFAULTS)
        if isinstance(config, dict):
            self.cfg.update({k: v for k, v in config.items() if k in DEFAULTS})
        file_cfg = _load_json("/AstrBot/data/config/astrbot_proactive_v2_config.json", {})
        if isinstance(file_cfg, dict):
            self.cfg.update({k: v for k, v in file_cfg.items() if k in DEFAULTS})
        self.db = DB()
        self._tok = {"p": 0, "c": 0}
        self._task = None
        self._busy = False
        self._group_active = {}
        self._last_user_at = float(self.db.get_state("last_user_at", 0) or 0)

    async def initialize(self):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % HIST_DB, uri=True)
            row = con.execute(
                "select max(created_at) from platform_message_history where user_id=? and content like ?",
                (self.cfg["umo"], '%"type": "user"%'),
            ).fetchone()
            if row and row[0]:
                import calendar

                dt = datetime.strptime(str(row[0])[:19], "%Y-%m-%d %H:%M:%S")
                self._last_user_at = max(self._last_user_at, calendar.timegm(dt.timetuple()) + 8 * 3600)
                self.db.set_state("last_user_at", self._last_user_at)
        except Exception:
            pass
        self._write_interests_md()
        if not getattr(self, "_gap_min", None):
            self._gap_min = float(self.db.get_state("gap_min", 0) or 0) or \
                float(self.cfg.get("interval_mean_minutes") or 90)
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
        logger.info(
            "[主动v2] 已启动：间隔均值 %s 分钟（范围 %s-%s，指数分布），%s-%s 点，每天≤%s 条（其中自己刷≤%s 条、在意的事≤%s 条），联网=%s"
            % (
                self.cfg["interval_mean_minutes"],
                self.cfg["interval_min_minutes"],
                self.cfg["interval_max_minutes"],
                self.cfg["active_hour_start"],
                self.cfg["active_hour_end"],
                self.cfg["max_per_day"],
                self.cfg["own_share_per_day"],
                self.cfg["focus_per_day"],
                self.cfg["web_enabled"],
            )
        )

    async def terminate(self):
        if self._task:
            self._task.cancel()
            self._task = None

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def _observe(self, event: AstrMessageEvent):
        try:
            if event.unified_msg_origin != self.cfg["umo"]:
                return
            self._last_user_at = _now()
            self.db.set_state("last_user_at", self._last_user_at)
            logs = self.db.last_logs(1)
            if logs and self._last_user_at - logs[0]["ts"] < 2 * 3600:
                self.db.mark_replied()
        except Exception:
            pass

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def _observe_group(self, event: AstrMessageEvent):
        """记录群里的动静：群里正在聊的时候别插话。"""
        try:
            umo = event.unified_msg_origin
            ga = getattr(self, "_group_active", None)
            if ga is None:
                ga = self._group_active = {}
            for t in self._targets():
                if t["kind"] == "group" and t["umo"] == umo:
                    ga[umo] = _now()
                    self.db.set_state("group_active:" + umo, ga[umo])
                    break
        except Exception:
            pass

    async def _loop(self):
        await asyncio.sleep(20)
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[主动v2] 调度异常：\n%s" % traceback.format_exc())
            await asyncio.sleep(60)

    def _roll_gap(self):
        """下一次主动消息要等多久：以均值为中心的指数分布，再夹在 [min, max] 之间。"""
        mean = float(self.cfg.get("interval_mean_minutes") or 90)
        lo = float(self.cfg.get("interval_min_minutes") or 30)
        hi = float(self.cfg.get("interval_max_minutes") or 120)
        try:
            u = random.random() or 1e-9
            # 指数分布叠在最短间隔上，再截到上限：均值≈(lo+mean)-mean*e^-(hi-lo)/mean
            gap = lo + min(hi - lo, -mean * math.log(u))
        except Exception:
            gap = mean
        self._gap_min = gap
        try:
            self.db.set_state("gap_min", round(gap, 1))
        except Exception:
            pass
        logger.info("[主动v2] 下次最早在 %.0f 分钟后（均值 %.0f，上限 %.0f）"
                    % (gap, mean, hi))

    def _can_fire(self):
        now = datetime.now()
        if not self.cfg["enabled"]:
            return False, "已关闭"
        if not (self.cfg["active_hour_start"] <= now.hour < self.cfg["active_hour_end"]):
            return False, "不在活跃时段"
        if self.db.today_count() >= self.cfg["max_per_day"]:
            return False, "今天已到上限"
        gap = getattr(self, "_gap_min", None) or float(self.cfg.get("interval_mean_minutes") or 90)
        idle = _now() - (self._last_user_at or 0)
        if idle < gap * 60:
            return False, "还没到这次的时间（空闲 %.0f 分钟 / 门槛 %.0f）" % (idle / 60, gap)
        last = self.db.last_logs(1)
        if last and _now() - last[0]["ts"] < self.cfg["min_gap_after_proactive_minutes"] * 60:
            return False, "距上次主动消息太近"
        return True, "ok"

    async def _tick(self):
        if self._busy:
            return
        ok, _why = self._can_fire()
        if not ok:
            return
        self._busy = True
        try:
            await self._fire()
        finally:
            self._busy = False

    # ---------------- 选题 ----------------
    async def _pick(self, provider, allow_types=None):
        umo = self.cfg["umo"]
        pending = {p["memory_id"]: p for p in self.db.pending_rows()}
        cands = Memory.pending_candidates(umo)
        for c in cands:
            st = pending.get(c["id"], {})
            c["status"] = st.get("status", "open")
            c["user_words"] = st.get("user_words", "")
            c["nudge_count"] = st.get("nudge_count", 0)
        payload = {
            "现在": datetime.now().strftime("%Y-%m-%d %H:%M %A"),
            "可选类型": allow_types or ["pending", "interest", "curiosity", "care", "focus"],
            "最近对话": ["%s: %s" % (w, t) for w, t in Memory.recent_dialogue(umo, self.cfg["recent_dialogue"])],
            "未完成事项": cands,
            "我在意但一直还悬着的事（来自我自己的自我，可以选 focus 类型）": self._focus_items(),
            "记忆里的兴趣": Memory.interests(umo, 10),
            "我上次主动说的": [
                {"时间": datetime.fromtimestamp(l["ts"]).strftime("%m-%d %H:%M"), "内容": l["text"]}
                for l in self.db.last_logs(3)
            ],
        }
        resp = await provider.text_chat(
            prompt=json.dumps(payload, ensure_ascii=False, indent=1),
            system_prompt=PICK_SYS,
            session_id="proactive-pick-%d" % random.randint(1, 10 ** 6),
            persist=False,
        )
        self._acc(resp)
        raw = (getattr(resp, "completion_text", "") or "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        for u in data.get("updates") or []:
            mid, st = u.get("memory_id"), u.get("status")
            if isinstance(mid, int) and st in ("deferred", "done", "open"):
                self.db.upsert_pending(mid, st, (u.get("user_words") or "")[:20])
                logger.info("[主动v2] 状态更新 memory=%s → %s「%s」" % (mid, st, u.get("user_words") or ""))
        for u in data.get("focus_updates") or []:
            self._apply_focus_update(u)

        pick = data.get("pick") or {}
        if pick.get("type") == "focus":
            topic = (pick.get("focus") or "").strip()
            items = {it["topic"]: it for it in self._focus_items()}
            hit = items.get(topic)
            if not hit:
                # 模型把话题改写了，做一次宽松匹配
                for k, v in items.items():
                    if k[:6] and (k[:6] in topic or topic[:6] in k):
                        hit, topic = v, k
                        break
            st = self.db.focus_get(topic) if hit else None
            now = _now()
            wait_h = float(self.cfg.get("focus_wait_hours") or 24)
            retry_min = float(self.cfg.get("focus_retry_minutes") or 90)
            if not hit:
                pick = {"type": "care", "memory_id": None, "reason": "在意的事对不上号，换成关心"}
            elif st and st["status"] == "dropped":
                pick = {"type": "care", "memory_id": None, "reason": "这件事已经了结了"}
            elif self.db.focus_today() >= int(self.cfg.get("focus_per_day") or 1):
                pick = {"type": "care", "memory_id": None, "reason": "今天已经问过一件悬着的事了"}
            elif st and st["status"] == "waiting" and now - (st["asked_at"] or 0) < wait_h * 3600:
                pick = {"type": "care", "memory_id": None, "reason": "还在等结果，催也没用"}
            elif st and st["status"] == "asked" and now - (st["asked_at"] or 0) < retry_min * 60:
                pick = {"type": "care", "memory_id": None, "reason": "刚问过，等他回"}
            else:
                pick = {
                    "type": "focus",
                    "memory_id": None,
                    "focus": topic,
                    "since": hit.get("since", ""),
                    "asked_before": int(st["asked_count"] or 0) if st else 0,
                    "reason": pick.get("reason", ""),
                    "angle": pick.get("angle", ""),
                }
        if pick.get("type") == "pending" and isinstance(pick.get("memory_id"), int):
            st = pending.get(pick["memory_id"], {})
            if st.get("status") == "deferred":
                cooled = _now() - (st.get("last_nudged_at") or 0) > self.cfg["deferred_cooldown_hours"] * 3600
                if not cooled:
                    logger.info("[主动v2] 否决 pick：待办 %s 处于 deferred 冷却期" % pick["memory_id"])
                    pick = {"type": "care", "memory_id": None, "reason": "那条待办他已表态，换成关心"}
        if allow_types and pick.get("type") not in allow_types:
            logger.info("[主动v2] 类型 %s 不适用于当前场景，换成 care" % pick.get("type"))
            pick = {"type": "care", "memory_id": None, "reason": "换个适合这里的话题"}
        return pick

    async def _pick_own(self, provider):
        """自己刷热榜并挑一条。返回 (pick, titles, query)。"""
        query, titles = browse(self.cfg)
        if not titles:
            return None, [], query
        payload = {
            "现在": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "热榜标题": titles,
            "我以前的兴趣": self.db.interests(8),
            "我昨天/刚才说过": [l["text"] for l in self.db.last_logs(3)],
        }
        resp = await provider.text_chat(
            prompt=json.dumps(payload, ensure_ascii=False, indent=1),
            system_prompt=BROWSE_SYS,
            session_id="proactive-browse-%d" % random.randint(1, 10 ** 6),
            persist=False,
        )
        self._acc(resp)
        self._acc(resp)
        raw = (getattr(resp, "completion_text", "") or "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except Exception:
            data = {}
        title = (data.get("pick_title") or "").strip()
        if not title:
            self.db.log_browse(query, titles, "", data.get("reason", ""))
            return None, titles, query
        interest = data.get("interest") or {}
        if interest.get("topic"):
            self.db.bump_interest(interest.get("topic"), interest.get("note", ""), self.cfg["interest_max"])
            self._write_interests_md()
            logger.info("[主动v2] 新兴趣「%s」：%s" % (interest.get("topic"), interest.get("note", "")))
        pick = {
            "type": "own",
            "memory_id": None,
            "reason": data.get("reason", ""),
            "angle": "分享我刚刷到的东西",
            "focus": title,
        }
        return pick, titles, query

    def _acc(self, resp):
        """累计一次调用的 token。"""
        if not isinstance(getattr(self, "_tok", None), dict):
            self._tok = {"p": 0, "c": 0}
        u = getattr(resp, "usage", None) or {}
        try:
            p = int(u.get("prompt_tokens") or 0) if hasattr(u, "get") else int(getattr(u, "prompt_tokens", 0) or 0)
            c = int(u.get("completion_tokens") or 0) if hasattr(u, "get") else int(getattr(u, "completion_tokens", 0) or 0)
        except Exception:
            p = c = 0
        self._tok["p"] += p
        self._tok["c"] += c
        return p, c

    def _apply_focus_update(self, u):
        """模型对「在意的事」的判断：了结就删、还要等就挂起、没回应就继续开放。"""
        topic = (u.get("topic") or "").strip()
        st = (u.get("status") or "").strip()
        if not topic or st not in ("resolved", "waiting", "open"):
            return
        if st == "resolved":
            removed = self._drop_focus_line(topic)
            self.db.focus_set(topic, "dropped", note=(u.get("note") or "")[:60])
            logger.info("[主动v2] 在意的事已了结「%s」%s" % (topic, "（已从自我里移除）" if removed else ""))
        else:
            self.db.focus_set(topic, st, note=(u.get("note") or "")[:60])
            logger.info("[主动v2] 在意的事「%s」→ %s %s" % (topic, st, u.get("note") or ""))

    def _drop_focus_line(self, topic):
        """从 self.md 的【近期关注】里删掉这一条。返回是否删掉。"""
        try:
            with open(SELF_PATH, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return False
        key = topic[:6]
        lines = text.splitlines()
        out, removed, in_block = [], False, False
        for ln in lines:
            if ln.strip().startswith("【"):
                in_block = ln.strip().startswith("【近期关注】")
            if in_block and ln.strip().startswith("-") and (key in ln):
                removed = True
                continue
            out.append(ln)
        if not removed:
            return False
        tmp = SELF_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(out) + "\n")
            os.replace(tmp, SELF_PATH)
            return True
        except Exception as e:
            logger.warning("[主动v2] 改写 self.md 失败：%s" % e)
            return False

    def _focus_items(self):
        """从自我里读「近期关注」——那些一直惦记、还没了结的事。"""
        if not self.cfg.get("focus_enabled"):
            return []
        try:
            with open(SELF_PATH, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return []
        m = re.search(r"【近期关注】(.*?)(?=\n【|\Z)", text, re.S)
        if not m:
            return []
        out = []
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line.startswith("-"):
                continue
            item = line.lstrip("-").strip()
            since = ""
            mm = re.search(r"[（(](\d{4}-\d{2}-\d{2})[）)]", item)
            if mm:
                since = mm.group(1)
                item = (item[: mm.start()] + item[mm.end():]).strip()
            item = item.rstrip("。 ")
            if len(item) < 3:
                continue
            out.append({"topic": item[:40], "since": since})
        return out

    async def _dive(self, pick):
        """顺手查一下这条到底是什么，拿到正文片段。"""
        if not self.cfg.get("deep_dive"):
            return ""
        q = (pick.get("focus") or "").strip()
        if not q:
            return ""
        try:
            items = await asyncio.to_thread(_mcp_snippets, q, int(self.cfg.get("dive_results") or 2))
        except Exception as e:
            logger.warning("[主动v2] 深挖失败：%s" % e)
            return ""
        parts = []
        for it in items:
            b = re.sub(r"\s+", " ", it.get("body") or "")
            b = re.sub(r"(URL Source:.*|Markdown Source:.*|Markdown Content:.*)", " ", b)
            b = b.strip()
            if len(b) >= 60:
                parts.append("《%s》：%s" % (it.get("title", "")[:40], b))
        txt = "\n".join(parts)[: int(self.cfg.get("dive_chars") or 500)]
        if txt:
            logger.info("[主动v2] 深挖「%s」→ %d 字" % (q[:24], len(txt)))
        return txt

    async def _veto(self, provider, pick, digest="", thought=""):
        """开口前再判一次：这句现在到底值不值得说。返回 (say, why)。"""
        if not self.cfg.get("veto_step"):
            return True, ""
        if self.cfg.get("veto_own_only") and pick.get("type") != "own":
            return True, ""
        body = {
            "现在": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "想说的这条": pick.get("focus", ""),
            "为什么想聊": pick.get("reason", ""),
            "我自己的反应": thought,
            "查到的内容": (digest or "")[:300],
            "我最近发过的": [l["text"] for l in self.db.last_logs(4)],
        }
        try:
            resp = await provider.text_chat(
                prompt=json.dumps(body, ensure_ascii=False, indent=1),
                system_prompt=VETO_SYS,
                session_id="proactive-veto-%d" % random.randint(1, 10 ** 6),
                persist=False,
            )
            self._acc(resp)
            raw = (getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", raw, re.S)
            data = json.loads(m.group(0)) if m else {}
            say = bool(data.get("say", True))
            why = (data.get("why") or "")[:40]
            logger.info("[主动v2] 开口前判断 say=%s %s" % (say, why))
            return say, why
        except Exception as e:
            logger.warning("[主动v2] 判断失败，默认说：%s" % e)
            return True, ""

    async def _think(self, provider, pick, digest=""):
        """先自己想一想为什么想说这条，再开口。"""
        if not self.cfg.get("think_step"):
            return ""
        body = {
            "刷到的": pick.get("focus", ""),
            "为什么戳到我": pick.get("reason", ""),
            "我顺手查到的": (digest or "")[:300],
        }
        try:
            resp = await provider.text_chat(
                prompt=json.dumps(body, ensure_ascii=False, indent=1),
                system_prompt=THINK_SYS,
                session_id="proactive-think-%d" % random.randint(1, 10 ** 6),
                persist=False,
            )
            self._acc(resp)
            txt = (getattr(resp, "completion_text", "") or "").strip()
            return txt.split("\n")[0][:120]
        except Exception as e:
            logger.warning("[主动v2] 想一步失败：%s" % e)
            return ""

    def _write_interests_md(self):
        try:
            rows = self.db.interests(self.cfg["interest_max"])
            if not rows:
                return
            lines = ["# 我自己在看的", ""]
            for r in rows:
                lines.append("- %s（权重 %s，主动提过 %s 次）%s" % (r["topic"], r["weight"], r["picked"], ("：" + r["note"]) if r["note"] else ""))
            os.makedirs(os.path.dirname(INTERESTS_MD), exist_ok=True)
            tmp = INTERESTS_MD + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, INTERESTS_MD)
        except Exception as e:
            logger.warning("[主动v2] 写 interests.md 失败：%s" % e)

    # ---------------- 生成 ----------------
    async def _compose(self, provider, pick, web_digest="", digest="", thought="", scene=None):
        last_texts = [l["text"] for l in self.db.last_logs(3)]
        own = pick.get("type") == "own"
        focus = pick.get("type") == "focus"
        extra = ""
        if own:
            extra = "你刚刷到的这条是：%s。你可以有点自己的判断，别当新闻播报。" % pick.get("focus", "")
            if digest:
                extra += "\n你顺手查到的相关内容（只用得上的部分，别照搬）：\n%s" % digest
            if thought:
                extra += "\n你刚才自己的想法：%s" % thought
        elif focus:
            extra = ("这是你自己心里惦记了好几天、一直没了结的事：%s。"
                     "直接开口把它问清楚，一句话就能了结的那种。别铺垫、别提『我一直惦记』。" % pick.get("focus", ""))
        elif web_digest:
            extra = "你可以引用这条刚看到的信息（别当新闻播报，只挑一句和话题有关的）：\n%s" % web_digest
        if scene == "group":
            extra += ("\n这是发在一个群里的：几个人都在，别用只对一个人说话的口气，"
                      "不要提只有某一个人知道的私事，也别单独点某个人名让人尴尬。")
        body = {
            "话题类型": pick.get("type"),
            "为什么想聊这个": pick.get("reason", ""),
            "打算怎么开口": pick.get("angle", ""),
            "焦点": pick.get("focus", ""),
            "我最近说过的（不要重复）": last_texts,
        }
        sys_prompt = (REPLY_SYS_OWN if own else REPLY_SYS).format(max_chars=self.cfg["max_chars"], extra=extra)
        prompt = json.dumps(body, ensure_ascii=False, indent=1)
        resp = await provider.text_chat(
            prompt=prompt,
            system_prompt=sys_prompt,
            session_id="proactive-say-%d" % random.randint(1, 10 ** 6),
            persist=False,
        )
        text = (getattr(resp, "completion_text", "") or "").strip()
        text = re.sub(r"^[\"'“”「」]+|[\"'“”「」]+$", "", text).strip()
        text = text.split("\n")[0][: self.cfg["max_chars"] * 2]
        for old in last_texts:
            if old and difflib.SequenceMatcher(None, text, old).ratio() > 0.6:
                resp = await provider.text_chat(
                    prompt=prompt + "\n（上一版和之前的太像了，换个说法，别重复句式）",
                    system_prompt=sys_prompt,
                    session_id="proactive-say-%d" % random.randint(1, 10 ** 6),
                    persist=False,
                )
                text = (getattr(resp, "completion_text", "") or "").strip()
                text = re.sub(r"^[\"'“”「」]+|[\"'“”「」]+$", "", text).strip().split("\n")[0]
                break
        return text[: self.cfg["max_chars"]]

    def _targets(self):
        raw = self.cfg.get("targets") or []
        out = []
        for t in raw:
            umo = (t.get("umo") or "").strip()
            if not umo:
                continue
            out.append({
                "umo": umo,
                "label": t.get("label") or ("群聊" if ":GroupMessage:" in umo else "私聊"),
                "kind": t.get("kind") or ("group" if ":GroupMessage:" in umo else "private"),
                "weight": float(t.get("weight") or 1),
                "max_per_day": int(t.get("max_per_day") or self.cfg["max_per_day"]),
                "types": t.get("types"),
            })
        if not out:
            out = [{"umo": self.cfg["umo"], "label": "私聊", "kind": "private",
                    "weight": 1, "max_per_day": self.cfg["max_per_day"], "types": None}]
        return out

    def _choose_target(self):
        cands = []
        ga = getattr(self, "_group_active", None) or {}
        idle_min = float(self.cfg.get("group_idle_minutes") or 30)
        for t in self._targets():
            used = self.db.today_count(target=t["umo"])
            if used >= t["max_per_day"]:
                continue
            if t["kind"] == "group":
                last = ga.get(t["umo"]) or \
                    float(self.db.get_state("group_active:" + t["umo"], 0) or 0)
                if last and _now() - last < idle_min * 60:
                    continue
            cands.append((t, t["weight"]))
        if not cands:
            return None
        total = sum(w for _, w in cands) or 1.0
        r = random.uniform(0, total)
        acc = 0.0
        for t, w in cands:
            acc += w
            if r <= acc:
                return t
        return cands[-1][0]

    async def _fire(self, force_own=False, target=None):
        provider = await self.context.get_using_provider_async()
        if provider is None:
            logger.warning("[主动v2] 没有可用模型，跳过")
            return
        tgt = target or self._choose_target()
        if tgt is None:
            logger.info("[主动v2] 今天各目标都到上限了，跳过")
            return
        allow = tgt.get("types")
        self._tok = {"p": 0, "c": 0}
        attempts = 1 + max(0, int(self.cfg.get("veto_retry") or 0))
        for attempt in range(attempts):
            before = self._tok["p"] + self._tok["c"]
            want_own = force_own or (
                self.cfg["own_share_enabled"]
                and self.db.own_today() < self.cfg["own_share_per_day"]
                and random.random() < self.cfg["own_share_ratio"]
            )
            pick, query, titles, digest, thought = None, "", [], "", ""
            if want_own:
                pick, titles, query = await self._pick_own(provider)
            if pick is None:
                pick = await self._pick(provider, allow_types=allow)
            if allow and pick.get("type") not in allow and pick.get("type") != "own":
                pick = {"type": "care", "memory_id": None,
                        "reason": "这是群聊，换个不涉及私事的话题"}
            if pick.get("type") == "own":
                digest = await self._dive(pick)
                thought = await self._think(provider, pick, digest)
            say, why = await self._veto(provider, pick, digest, thought)
            if not say:
                spent = self._tok["p"] + self._tok["c"] - before
                self.db.add_log("veto", None, why, "", bool(titles),
                                tokens=spent, kind_detail=pick.get("focus", "")[:60],
                                target=tgt["umo"])
                if pick.get("type") == "own":
                    self.db.log_browse(query, titles, pick.get("focus", ""), why, "")
                logger.info("[主动v2] 第 %d 次决定不说（花了 %d token）：%s" % (attempt + 1, spent, why))
                continue
            text = await self._compose(provider, pick, digest=digest, thought=thought,
                                       scene=tgt["kind"])
            if not text or len(text) < 4:
                logger.warning("[主动v2] 生成结果为空，放弃本次")
                return
            await self.context.send_message(tgt["umo"], MessageChain([Plain(text)]))
            mid = pick.get("memory_id") if isinstance(pick.get("memory_id"), int) else None
            total = self._tok["p"] + self._tok["c"]
            self.db.add_log(pick.get("type") or "other", mid, pick.get("angle", ""), text, bool(titles),
                            tokens=total, kind_detail=pick.get("focus", "")[:60], target=tgt["umo"])
            if mid:
                self.db.mark_nudged(mid)
            if pick.get("type") == "focus":
                self.db.add_focus(pick.get("focus", ""))
                self.db.focus_set(pick.get("focus", ""), "asked", bump_asked=True)
            if pick.get("type") == "own":
                self.db.log_browse(query, titles, pick.get("focus", ""), pick.get("reason", ""), text)
            self._roll_gap()
            logger.info("[主动v2] 已发送 → %s type=%s id=%s token=%d(p=%d,c=%d) 内容=%s"
                        % (tgt["label"], pick.get("type"), mid, total, self._tok["p"], self._tok["c"], text))
            return
        self._roll_gap()
        logger.info("[主动v2] 本次 %d 次尝试都决定不说，共花 %d token"
                    % (attempts, self._tok["p"] + self._tok["c"]))

    @filter.command("主动一次")
    async def manual_fire(self, event: AstrMessageEvent):
        """手动触发一条主动消息（调试用）。"""
        if event.get_sender_id() != self.cfg["umo"].split(":")[-1]:
            yield event.plain_result("只有主人能用。")
            return
        await self._fire()
        yield event.plain_result("已尝试发送一条主动消息（看日志）。")

    @filter.command("群主动")
    async def manual_group_fire(self, event: AstrMessageEvent):
        """手动往群里发一条主动消息（调试用）。"""
        if event.get_sender_id() != self.cfg["umo"].split(":")[-1]:
            yield event.plain_result("只有主人能用。")
            return
        tgt = next((t for t in self._targets() if t["kind"] == "group"), None)
        if not tgt:
            yield event.plain_result("没有配置群聊目标。")
            return
        await self._fire(target=tgt)
        yield event.plain_result("已尝试往「%s」发一条（看日志）。" % tgt["label"])

    @filter.command("刷一条")
    async def manual_browse(self, event: AstrMessageEvent):
        """强制走一次“自己刷热榜”的路径。"""
        if event.get_sender_id() != self.cfg["umo"].split(":")[-1]:
            yield event.plain_result("只有主人能用。")
            return
        await self._fire(force_own=True)
        yield event.plain_result("已尝试刷一条（看日志）。")
