"""astrbot_short_recall —— 48 小时短期回忆（只读）

设计要点：
- 不新建任何存储：直接只读 AstrBot 自带的 platform_message_history 表。
- 不打分、不设 importance：短期记忆是事实日志，不是判断结果。
- 按时间意图触发：只有用户问起"昨天/刚才/前几天"等才去翻，平时零成本。
- 隐私硬隔离：只查「该发送者参与过的会话」，绝不跨用户。

数据现实（已核实）：
- created_at 存的是 UTC，本地展示需 +8。
- user 行：sender_id = QQ 号，content.type = "user"
- bot 行：sender_id = "3952927705" 或 "bot"，content.type = "bot"
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

TZ = timezone(timedelta(hours=8))
DB_PATH = "/AstrBot/data/data_v4.db"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "max_items": 4,
    "max_tokens": 320,
    "max_candidates": 300,
    "min_score": 0.05,
}

# 时间词 → 相对窗口（左闭右开，本地时区）
_STOP = set("的了吗啊呢吧是我你他她它在有就不也都这个那个什么怎么为什么说讲过要会能可以而且但是所以因为如果然后现在时候")
_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_N_DAYS_RE = re.compile(r"(\d{1,2})\s*天前")

_RULES: list[tuple[str, str]] = [
    (r"刚才|刚刚|方才|刚说", "minutes60"),
    (r"昨天|昨晚|昨日|昨夜", "yesterday"),
    (r"前天", "day_before"),
    (r"今早|今天早上|今天上午|今天|今日|今晚|今天晚上", "today"),
    (r"上周|上个星期|上星期|上一周", "last_week"),
    (r"前几天|前些天", "days5"),
    (r"这周|本周|这几天|最近|近期", "days3"),
    # 没有明确时间词、但在回溯往事 —— 默认按近 72 小时翻
    (r"之前|上次|上回|那次|那天|记得|还记得|说过|提过|聊过|我说", "days3"),
]


def _keywords(text: str) -> set[str]:
    keys: set[str] = set()
    for m in _WORD_RE.finditer(text or ""):
        keys.add(m.group(0).lower())
    cjk = _CJK_RE.findall(text or "")
    for i, ch in enumerate(cjk):
        if ch not in _STOP:
            keys.add(ch)
        if i + 1 < len(cjk):
            pair = ch + cjk[i + 1]
            if ch not in _STOP and cjk[i + 1] not in _STOP:
                keys.add(pair)
    return {k for k in keys if k not in _STOP}


def _resolve_window(text: str, now_local: datetime) -> tuple[datetime, datetime, str] | None:
    """把时间词解析成 [start, end) 本地时间窗口。"""
    m = _N_DAYS_RE.search(text)
    if m:
        n = max(1, min(30, int(m.group(1))))
        end = (now_local - timedelta(days=n - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        return start, end, f"{n}天前"

    for pattern, kind in _RULES:
        if not re.search(pattern, text):
            continue
        if kind == "minutes60":
            return now_local - timedelta(minutes=60), now_local, "刚才"
        if kind == "today":
            start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, now_local, "今天"
        if kind == "yesterday":
            start = (now_local - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1), "昨天"
        if kind == "day_before":
            start = (now_local - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1), "前天"
        if kind == "last_week":
            start = (now_local - timedelta(days=14)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (now_local - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, end, "上周"
        if kind == "days5":
            return now_local - timedelta(days=5), now_local, "前几天"
        if kind == "days3":
            return now_local - timedelta(days=3), now_local, "这几天"
    return None


def _text_of(content: str) -> tuple[str, str]:
    """从 content JSON 提取 (role, 纯文本)。"""
    try:
        obj = json.loads(content)
    except Exception:
        return "", ""
    role = obj.get("type") or ""
    parts: list[str] = []
    for seg in obj.get("message") or []:
        if not isinstance(seg, dict):
            continue
        seg_type = seg.get("type")
        if seg_type == "at":
            continue  # @某人 对回忆无信息量，丢掉
        raw = str(seg.get("text") or "").strip()
        if raw in ("[at]", "@"):
            continue
        if raw:
            parts.append(raw)
        elif seg_type not in ("plain", None):
            parts.append(f"[{seg_type}]")
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return role, text


def _fmt_local(utc_str: str) -> str:
    try:
        dt = datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).strftime("%m-%d %H:%M")
    except Exception:
        return utc_str[:16]


def _utc_str(dt_local: datetime) -> str:
    return dt_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class ShortRecallDB:
    """只读查询。全部同步 sqlite3，调用方放进线程池。"""

    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def sessions_of(self, sender_id: str) -> list[str]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT user_id FROM platform_message_history "
                "WHERE sender_id = ? OR user_id = ? OR user_id LIKE ?",
                (sender_id, sender_id, f"%:{sender_id}"),
            ).fetchall()
            return [r["user_id"] for r in rows if r["user_id"]]
        finally:
            conn.close()

    def fetch(self, sessions: list[str], start_utc: str, end_utc: str, limit: int) -> list[dict]:
        if not sessions:
            return []
        marks = ",".join("?" * len(sessions))
        sql = (
            "SELECT id, user_id, sender_id, sender_name, content, created_at "
            f"FROM platform_message_history WHERE user_id IN ({marks}) "
            "AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at DESC LIMIT ?"
        )
        conn = self._conn()
        try:
            rows = conn.execute(sql, (*sessions, start_utc, end_utc, limit)).fetchall()
        finally:
            conn.close()
        out = []
        for r in rows:
            role, text = _text_of(r["content"])
            if not text:
                continue
            out.append({
                "id": r["id"],
                "session": r["user_id"],
                "sender_id": r["sender_id"],
                "sender_name": r["sender_name"],
                "role": role,
                "text": text,
                "created_at": r["created_at"],
            })
        return out

    def recent_any(self, sessions: list[str], hours: int, limit: int) -> list[dict]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        return self.fetch(sessions, start.strftime("%Y-%m-%d %H:%M:%S"),
                          end.strftime("%Y-%m-%d %H:%M:%S"), limit)


@register("astrbot_short_recall", "dsh", "48 小时短期回忆（只读，不写入任何数据）", "v0.1.0")
class ShortRecall(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.cfg = dict(DEFAULTS)
        if isinstance(config, dict):
            self.cfg.update({k: v for k, v in config.items() if k in DEFAULTS})
        self.db = ShortRecallDB()

    # ------------------------------------------------------------------ 内部

    def _select(self, rows: list[dict], query: str, max_items: int, min_score: float,
                prefer_sender: str | None) -> list[dict]:
        if not rows:
            return []
        qkeys = _keywords(query)
        scored = []
        for r in rows:
            keys = _keywords(r["text"])
            overlap = len(qkeys & keys)
            score = overlap / max(1, len(qkeys)) if qkeys else 0.0
            if prefer_sender and r["sender_id"] == prefer_sender:
                score += 0.15  # 用户自己的话优先于别人的
            scored.append((score, r))
        if qkeys and any(s >= min_score for s, _ in scored):
            scored = [x for x in scored if x[0] >= min_score]
        # 分数相同则按时间倒序（rows 本身已按时间倒序）
        scored.sort(key=lambda pair: (-pair[0],))
        picked = [r for _, r in scored[:max_items]]
        picked.sort(key=lambda r: r["created_at"])
        return picked

    def _lines(self, picked: list[dict], budget: int) -> list[str]:
        lines: list[str] = []
        used = 0
        seen: set[str] = set()
        for r in picked:
            body = r["text"][:220]
            norm = re.sub(r"\s+", "", body)
            if norm in seen:  # 同一句话重复发/被引用，只留一条
                continue
            seen.add(norm)
            who = "大肥鱼" if r["role"] == "bot" else (r["sender_name"] or r["sender_id"])
            line = f"[{_fmt_local(r['created_at'])}] {who}: {body}"
            if used + len(line) > budget and lines:
                break
            used += len(line)
            lines.append(line)
        return lines

    def _render(self, picked: list[dict], label: str, budget: int) -> str:
        lines = self._lines(picked, budget)
        if not lines:
            return ""
        head = [
            "<recent_memory>",
            f"以下是用户「{label}」的真实对话摘录（时间已换算为本地时间）。"
            "仅在用户问及过去的事情时参考；引用时请说出具体日期时间，"
            "不要编造摘录之外的内容。若摘录里没有相关信息，就直说记不清。",
        ]
        return "\n".join(head + lines + ["</recent_memory>"])

    async def _build(self, query: str, sender_id: str, window: tuple[datetime, datetime, str] | None,
                     max_items: int, budget: int) -> tuple[str, list[dict], str]:
        sessions = await asyncio.to_thread(self.db.sessions_of, sender_id)
        if not sessions:
            return "", [], ""
        if window:
            start, end, label = window
            rows = await asyncio.to_thread(
                self.db.fetch, sessions, _utc_str(start), _utc_str(end),
                int(self.cfg["max_candidates"]),
            )
        else:
            label = "最近48小时"
            rows = await asyncio.to_thread(
                self.db.recent_any, sessions, 48, int(self.cfg["max_candidates"]),
            )
        picked = self._select(rows, query, max_items, float(self.cfg["min_score"]), sender_id)
        return self._render(picked, label, budget), picked, label

    # ------------------------------------------------------------------ 钩子

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self.cfg.get("enabled", True):
            return
        try:
            text = str(getattr(req, "prompt", "") or event.message_str or "").strip()
            if not text:
                return
            now_local = datetime.now(TZ)
            window = _resolve_window(text, now_local)
            if window is None:
                return  # 没问过去的事，零成本退出
            pack, picked, label = await self._build(
                text, str(event.get_sender_id() or ""), window,
                int(self.cfg["max_items"]), int(self.cfg["max_tokens"]),
            )
            if not pack:
                logger.info("[短期回忆] 命中「%s」但窗口内无记录", label)
                return
            req.system_prompt = f"{req.system_prompt}\n\n{pack}".strip()
            logger.info("[短期回忆] 命中「%s」，注入 %d 条（%d chars）", label, len(picked), len(pack))
        except Exception:
            logger.exception("[短期回忆] 注入失败（不影响聊天）")

    # ------------------------------------------------------------------ LLM 工具

    @filter.llm_tool(name="recall_recent_conversation")
    async def tool_recall_recent(self, event: AstrMessageEvent, query: str, days: int = 2) -> str:
        """翻查最近几天的真实聊天原文（短期回忆）。当用户提到过去发生过的事、你记不清刚才/之前的上下文、或需要核对细节时调用。要具体人名、装备、事件经过这类事实，优先用本工具，不要凭空猜测。

        Args:
            query(string): 要查找的关键词，例如“宠物小鸡”“海月”；留空则返回最近几条
            days(number): 往回翻多少天，默认 2，最多 7
        """
        if not self.cfg.get("enabled", True):
            return "（短期回忆功能已关闭）"
        try:
            span = float(days or 2)
            span = max(0.02, min(span, 7.0))
            now_local = datetime.now(TZ)
            window = (now_local - timedelta(days=span), now_local, f"最近{span:g}天")
            _, picked, label = await self._build(
                query or "", str(event.get_sender_id() or ""), window,
                int(self.cfg["max_items"]), int(self.cfg["max_tokens"]),
            )
            lines = self._lines(picked, int(self.cfg["max_tokens"]))
            if not lines:
                logger.info("[短期回忆] 工具调用「%s」%s：无记录", query, label)
                return "（这段时间的聊天里没有查到相关内容）"
            logger.info("[短期回忆] 工具调用「%s」%s：返回 %d 条", query, label, len(lines))
            return "以下是最近的真实聊天记录（时间为本地时间，仅可据此作答，不要编造）：\n" + "\n".join(lines)
        except Exception:
            logger.exception("[短期回忆] 工具调用失败")
            return "（短期回忆检索出错）"
