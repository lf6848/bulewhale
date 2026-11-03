# -*- coding: utf-8 -*-
"""astrbot_brain_read —— 把「自我档案」和「日记」读进模型。

写入侧由宿主机 /usr/local/bin/brain-night.py 负责（每天 04:40）。
本插件只读，不改任何文件；开关分开，便于单独灰度。

日记的选材按「问题指向哪一天/哪个主题」来挑，不是一律取最近一篇：
  昨天/昨晚 → 前一天   前天 → 前两天   上周 → 上周整天
  N 天前 → 那一天      记得/之前/那个… → 用索引做主题匹配
  问原话/承诺 → 不注入日记，交给 short_recall 取原始消息
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

DEFAULT_BRAIN = "/AstrBot/data/plugin_data/astrbot_brain"
INTERESTS_MD = "/AstrBot/data/plugin_data/astrbot_proactive_v2/interests.md"

SELF_MARK = "<!--self-profile-->"
DIARY_MARK = "<brain_diary>"

DEFAULTS = {
    "enabled": True,
    "inject_self": True,
    "inject_diary": True,
    "inject_user_ids": [],
    "inject_interests": True,
    "interests_max_chars": 400,
    "self_max_chars": 700,
    "diary_max_chars": 300,
    "diary_expand_chars": 800,
    "diary_index_days": 3,
    # 问"原话/承诺"时，原文在消息历史里，日记反而会干扰
    "raw_hints": ["原话", "承诺", "答应", "怎么说的", "我说过", "说了什么"],
    # 问事实（住哪/叫什么/几岁）时，答案在事实库里，日记只会串味
    "fact_hints": ["住哪", "住在", "哪个城市", "什么地方", "叫什么", "名字", "几岁",
                   "多大", "多少岁", "在哪上", "哪个学校"],
    "expand_hints": ["复盘", "详细", "那几天", "发生了什么"],
    "time_hints": ["昨天", "昨晚", "前天", "上周", "那天", "之前", "记得", "以前",
                   "最近", "前几天", "上次", "上回"],
}


def _read(path: str, limit: int) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read().strip()
    except Exception:
        return ""
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "……"
    return s


def _chars(text: str) -> set:
    """中文二元组 + ASCII 词，用来做主题粗匹配（中文没有空格，单字噪音太大）。"""
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", text or "")
    grams = {t[i:i + 2] for i in range(len(t) - 1)}
    grams |= {w.lower() for w in re.findall(r"[A-Za-z]{2,}", text or "")}
    return grams


class _FileCache:
    """按 mtime 缓存小文件，避免每轮都读盘。"""

    def __init__(self) -> None:
        self._memo: dict[str, tuple[float, str]] = {}

    def get(self, path: str, limit: int) -> str:
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return ""
        hit = self._memo.get(path)
        if hit and hit[0] == mt:
            return hit[1]
        text = _read(path, limit)
        self._memo[path] = (mt, text)
        return text


@register(
    "astrbot_brain_read",
    "dsh",
    "把自我档案与日记读进模型（只读；日记按问题指向的日期/主题选材）",
    "v0.2.0",
)
class BrainRead(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.cfg = dict(DEFAULTS)
        try:
            if config:
                for k in list(self.cfg):
                    if k in config:
                        self.cfg[k] = config[k]
        except Exception:
            pass
        self._load_cfg_file()
        self.brain = os.environ.get("BRAIN_DIR") or DEFAULT_BRAIN
        self.cache = _FileCache()
        logger.info(
            "[大脑] 已加载 self=%s diary=%s 白名单=%s",
            self.cfg.get("inject_self"),
            self.cfg.get("inject_diary"),
            self.cfg.get("inject_user_ids") or "全部",
        )

    # ---------- 配置 ----------

    def _load_cfg_file(self) -> None:
        """AstrBot 没有传 config 时，直接读配置文件。"""
        cands = [os.environ.get("BRAIN_CFG") or "",
                 "/AstrBot/data/config/astrbot_brain_read_config.json"]
        for path in cands:
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k in list(self.cfg):
                        if k in data:
                            self.cfg[k] = data[k]
                    return
            except Exception as e:
                logger.warning("[大脑] 读取配置失败 %s: %s", path, e)

    # ---------- 文件读取 ----------

    def _self_text(self) -> str:
        body = self.cache.get(os.path.join(self.brain, "self.md"),
                              int(self.cfg.get("self_max_chars") or 700))
        if not body:
            return ""
        if self.cfg.get("inject_interests", True):
            extra = self.cache.get(INTERESTS_MD, int(self.cfg.get("interests_max_chars") or 400))
            if extra:
                lines = [l for l in extra.splitlines() if l.strip() and not l.startswith("#")]
                if lines:
                    body = body.rstrip() + "\n\n【我自己最近在看的、在感兴趣的】\n" + "\n".join(lines)
        return body

    def _index_map(self) -> dict:
        raw = self.cache.get(os.path.join(self.brain, "diary_index.json"), 200000)
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _diary_text(self, day: str, limit: int) -> str:
        return self.cache.get(os.path.join(self.brain, "diary", day + ".md"), limit)

    # ---------- 选材 ----------

    def _today(self) -> date:
        return datetime.now().date()

    def _pick_days(self, text: str) -> list[str]:
        """把问句解析成具体日期；解析不出来就返回空，交给主题匹配。"""
        t = text or ""
        today = self._today()

        m = re.search(r"(\d{1,3})\s*天前", t)
        if m:
            return [(today - timedelta(days=int(m.group(1)))).isoformat()]
        if "前天" in t:
            return [(today - timedelta(days=2)).isoformat()]
        if "昨天" in t or "昨晚" in t:
            return [(today - timedelta(days=1)).isoformat()]
        if "大前天" in t:
            return [(today - timedelta(days=3)).isoformat()]

        if "上周" in t:
            # 上周一到上周日
            monday = today - timedelta(days=today.weekday() + 7)
            return [(monday + timedelta(days=i)).isoformat() for i in range(7)]

        if "前几天" in t or "最近" in t:
            return [(today - timedelta(days=i)).isoformat() for i in range(1, 4)]
        return []

    def _pick_by_topic(self, text: str) -> list[str]:
        """用索引做主题匹配，找最相关的一两天。"""
        idx = self._index_map()
        q = _chars(text)
        if not idx or not q:
            return []
        scored = []
        for day, one in idx.items():
            g = _chars(one or "")
            if not g:
                continue
            hit = len(q & g)
            if hit:
                scored.append((hit / (len(g) ** 0.5), day))
        scored.sort(reverse=True)
        return [d for _, d in scored[:2]]

    def _diary_block(self, text: str) -> str:
        """生成日记块；找不到合适材料就返回空（宁缺毋滥）。"""
        if any(h in (text or "") for h in self.cfg.get("raw_hints") or []):
            return ""
        if any(h in (text or "") for h in self.cfg.get("fact_hints") or []):
            return ""

        expand = any(h in (text or "") for h in self.cfg.get("expand_hints") or [])
        budget = int(self.cfg.get("diary_expand_chars" if expand else "diary_max_chars") or 400)

        explicit = self._pick_days(text)
        days = explicit or self._pick_by_topic(text)
        idx = self._index_map()

        have = [d for d in days if d in idx or self._diary_text(d, 10)]
        if not have:
            # 只允许「昨天/前天」这类近两天的问题退回最近一篇（且标题仍写真实日期）；
            # 更早的窗口或主题没命中，就当作没有材料，不要硬凑。
            near = [(self._today() - timedelta(days=i)).isoformat() for i in (1, 2)]
            if explicit and any(d in near for d in explicit):
                have = sorted(idx)[-1:]
            else:
                return ""

        if not have:
            return ""

        per = max(180, budget // max(1, len(have)))
        chunks = []
        for d in have[:3]:
            body = self._diary_text(d, per)
            if body:
                chunks.append(f"【{d} 的日记】\n{body}")
            elif idx.get(d):
                chunks.append(f"【{d} 的日记】\n{idx[d]}")
        if not chunks:
            return ""

        recent = []
        n = int(self.cfg.get("diary_index_days") or 3)
        for d in sorted(idx)[-n:]:
            if idx.get(d):
                recent.append(f"{d[5:]} {idx[d]}")

        parts = ["\n\n" + DIARY_MARK +
                 "\n（你写的日记，是你自己的记忆，不是对方说的；相关时自然带出，别逐条复述。）"]
        parts.extend(chunks)
        if recent:
            parts.append("【最近几天一句话】\n" + "\n".join(recent))
        return "\n\n".join(parts) + "\n</brain_diary>"

    # ---------- 判定 ----------

    def _allowed(self, event: AstrMessageEvent) -> bool:
        wl = self.cfg.get("inject_user_ids") or []
        if not wl:
            return True
        try:
            return str(event.get_sender_id()) in {str(x) for x in wl}
        except Exception:
            return False

    def _wants_diary(self, text: str) -> bool:
        if any(h in (text or "") for h in self.cfg.get("raw_hints") or []):
            return False
        if any(h in (text or "") for h in self.cfg.get("fact_hints") or []):
            return False
        hints = self.cfg.get("time_hints") or []
        return any(h and h in (text or "") for h in hints)

    # ---------- 注入 ----------

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        try:
            self._inject(event, req)
        except Exception as e:  # 任何异常都不能弄哑对话
            logger.warning("[大脑] 注入失败，本轮回退原样: %s", e)

    def _inject(self, event: AstrMessageEvent, req) -> None:
        if not self.cfg.get("enabled", True):
            return
        if not self._allowed(event):
            return

        self_chars = diary_chars = 0

        if self.cfg.get("inject_self", True):
            sp = req.system_prompt or ""
            if SELF_MARK not in sp:
                body = self._self_text()
                if body:
                    req.system_prompt = sp + (
                        f"\n\n{SELF_MARK}\n【关于我自己】\n{body}\n<!--/self-profile-->")
                    self_chars = len(body)

        if self.cfg.get("inject_diary", True) and self._wants_diary(getattr(event, "message_str", "")):
            p = req.prompt or ""
            if DIARY_MARK not in p:
                block = self._diary_block(getattr(event, "message_str", ""))
                if block:
                    req.prompt = p + block
                    diary_chars = len(block)

        umo = ""
        try:
            umo = event.unified_msg_origin
        except Exception:
            pass
        logger.info("[大脑] self=%d diary=%d umo=%s", self_chars, diary_chars, umo)
