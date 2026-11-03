"""astrbot_group_attention —— 群聊「是否在跟我说话」判定

替代 AstrBot 内置的固定概率主动回复（默认 10% 掷骰子）。
用 monkeypatch 替换 GroupChatContext.need_active_reply，不改任何核心文件。

判定顺序：
  1. 称呼命中（别名表 + 自学习别名）        → 直接回
  2. 引用了机器人自己的消息                  → 直接回
  3. 回复后 3 条跟进窗口                     → 让模型判「是不是接着跟我说」
  4. 出现「你/您」或疑问句                    → 让模型看上下文判
  5. 都不像                                  → 5% 底噪

自学习别名：模型判 YES 时会顺手抽出「它被叫什么」，同一称呼累计 2 次即转正。
配置：/AstrBot/data/config/astrbot_group_attention_config.json（热加载）
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import uuid

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.platform import MessageType
from astrbot.api.star import Context, Star, register

CONFIG_PATH = "/AstrBot/data/config/astrbot_group_attention_config.json"
LEARNED_PATH = "/AstrBot/data/plugin_data/astrbot_group_attention/learned_aliases.json"

DEFAULTS = {
    "enabled": True,
    "aliases": [
        "大肥鱼", "肥鱼", "大鱼", "小肥鱼", "肥鱼bot", "大肥魚",
        "小鲸鱼", "鲸鱼", "大鲸鱼", "肥鲸",
        "deepseek", "deep seek", "ds", "小ds", "ds老师",
    ],
    "pronouns": ["你", "您"],
    "llm_judge": True,
    "llm_provider_id": "",
    "cooldown_seconds": 8,
    "followup_window": 3,
    "followup_judge": True,
    "learn_aliases": True,
    "learn_min_count": 2,
    "fallback_probability": 0.05,
    "max_context_messages": 12,
    "timeout_seconds": 6,
    "respect_other_at": True,
}

_BAD_ALIAS = {
    "你", "您", "它", "他", "她", "我", "咱", "大家",
    "这个", "那个", "这里", "那里", "什么", "怎么", "为什么",
    "图片", "表情", "东西", "一下", "看看", "来吧", "好的",
}

_QUESTION = re.compile(
    r"[?？]|吗|呢|啥|怎么|为什么|为啥|哪|是不是|能不能|可不可以|有没有|要不要|多少|几点|咋"
)

_SYS = (
    "你在判断 QQ 群里最新的一条消息，是不是在跟机器人「大肥鱼」说话（期待它回复）。\n"
    "第一行只写 YES 或 NO。\n"
    "如果是 YES 且消息里用了对它的称呼（不是「你/您」这种代词），第二行写 ALIAS: 那个称呼；否则第二行写 ALIAS: -\n\n"
    "QQ 消息里的 @昵称(QQ号) 表示这条消息 @ 了那个群友；【本条引用了】表示它引用回复了某人某条消息。\n\n"
    "YES：直接叫了它的名字/外号；@ 的是它自己；用「你/您」明显指它；引用它的消息在跟它说话；回答它的问题或接着它的话题。\n"
    "NO：@ 的是别的群友（哪怕句子里有「你」，那个「你」指的是被 @ 的人）；引用的是别人的消息且在与那人对话；"
    "群友互相聊天、互相点名；单纯陈述、发表情；话题与它无关，它插话会突兀。"
)

_SYS_FOLLOWUP = (
    "机器人「大肥鱼」刚刚在这个 QQ 群里回复过。现在判断最新这条消息，是不是在接着跟它说话。\n"
    "第一行只写 YES 或 NO；若 YES 且消息里用了对它的称呼，第二行写 ALIAS: 那个称呼，否则写 ALIAS: -\n\n"
    "QQ 消息里的 @昵称(QQ号) 表示这条消息 @ 了那个群友；【本条引用了】表示它引用回复了某人某条消息。\n"
    "注意：如果本条 @ 的是别的群友、或者引用的是别人的消息并在跟那个人讲话，那就不算接着它说。\n\n"
    "YES：在回应/追问/反驳它刚才那句，或者话题明显还挂在它身上。\n"
    "NO：群友之间转向了新话题、@ 了别人跟别人说话、或者只是顺口一句与它无关的感叹。"
)


# --------------------------------------------------------------------- 配置/别名


def _load_cfg() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("[群聊注意] 读取配置失败，使用默认值")
    return cfg


def _load_learned() -> dict[str, int]:
    try:
        with open(LEARNED_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): int(v) for k, v in data.items()}
    except Exception:
        return {}


def _save_learned(data: dict[str, int]) -> None:
    try:
        os.makedirs(os.path.dirname(LEARNED_PATH), exist_ok=True)
        tmp = LEARNED_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LEARNED_PATH)
    except Exception:
        logger.exception("[群聊注意] 写入自学习别名失败")


def _bump_alias(alias: str, cfg: dict) -> None:
    alias = alias.strip().strip("「」\"'“”")
    if not cfg.get("learn_aliases", True):
        return
    if not (2 <= len(alias) <= 10) or alias in _BAD_ALIAS:
        return
    if alias in cfg["aliases"]:
        return
    data = _load_learned()
    data[alias] = data.get(alias, 0) + 1
    _save_learned(data)
    need = int(cfg.get("learn_min_count", 2))
    if data[alias] == need:
        logger.info("[群聊注意] 学会新称呼「%s」（累计 %d 次，已启用）", alias, need)


def _all_aliases(cfg: dict) -> list[str]:
    learned = _load_learned()
    need = int(cfg.get("learn_min_count", 2))
    extra = [a for a, c in learned.items() if c >= need]
    return list(cfg["aliases"]) + extra


def _alias_hit(text: str, aliases: list[str]) -> str | None:
    low = text.lower()
    for alias in aliases:
        a = alias.strip()
        if not a:
            continue
        if a.isascii():
            # 英文别名按词边界匹配，避免 ds 命中 dsh / ads
            if re.search(rf"(?<![a-z0-9]){re.escape(a.lower())}(?![a-z0-9])", low):
                return a
        elif a in text:
            return a
    return None


# --------------------------------------------------------------------- 判定核心


def _at_targets(event) -> tuple[list[tuple[str, str]], bool, bool]:
    """返回 (被@的其他人[(昵称, QQ)], 是否@了机器人, 是否@全体)。"""
    me = str(getattr(event.message_obj, "self_id", "") or "")
    others: list[tuple[str, str]] = []
    at_self = False
    at_all = False
    for seg in getattr(event.message_obj, "message", []) or []:
        if type(seg).__name__ != "At":
            continue
        qq = str(getattr(seg, "qq", "") or "")
        name = str(getattr(seg, "name", "") or "")
        if qq == "all":
            at_all = True
        elif me and qq == me:
            at_self = True
        elif qq:
            others.append((name or qq, qq))
    return others, at_self, at_all


def _quote_info(event) -> str:
    """本条消息引用了谁、引用的原文是什么（QQ 引用消息）。"""
    for seg in getattr(event.message_obj, "message", []) or []:
        if type(seg).__name__ != "Reply":
            continue
        who = str(getattr(seg, "sender_nickname", "") or "")
        body = str(getattr(seg, "message_str", "") or "").strip()
        if not body:
            chain = getattr(seg, "chain", None) or []
            body = "".join(
                str(getattr(c, "text", "") or "") for c in chain
                if type(c).__name__ == "Plain"
            ).strip()
        if who or body:
            return f"{who}：{body[:200]}" if who else body[:200]
    return ""


async def _is_reply_to_self(event) -> bool:
    try:
        me = str(event.message_obj.self_id or "")
        for seg in getattr(event.message_obj, "message", []) or []:
            if type(seg).__name__ != "Reply":
                continue
            rid = getattr(seg, "id", None)
            if not rid:
                continue
            bot = getattr(event, "bot", None)
            if bot is None:
                return False
            res = await asyncio.wait_for(bot.call_action("get_msg", message_id=rid), timeout=3)
            sender = str(((res or {}).get("sender") or {}).get("user_id") or "")
            return bool(me) and sender == me
    except Exception:
        return False
    return False


async def _judge(star: GroupAttention, ctx, event, text: str, cfg: dict,
                 followup: bool = False) -> tuple[bool | None, str | None]:
    """让模型看最近上下文判一次。返回 (verdict, alias)。verdict=None 表示放弃。"""
    umo = event.unified_msg_origin
    records = getattr(ctx, "raw_records", None) or {}
    recent = list(records.get(umo, []))[-int(cfg["max_context_messages"]):]
    lines = [str(r)[:300] for r in recent]
    speaker = event.get_sender_name() or event.get_sender_id()
    block = "【最近群聊】\n" + ("\n".join(lines) if lines else "（无）")
    block += f"\n\n【最新消息】{speaker}: {text[:400]}"
    quote = _quote_info(event)
    if quote:
        block += f"\n【本条引用了】{quote}"
    others, at_self, at_all = _at_targets(event)
    if others:
        block += "\n【本条@了】" + "、".join(f"{n}({q})" for n, q in others)
    if at_self:
        block += "\n【本条@了机器人自己】是"
    if at_all:
        block += "\n【本条@全体成员】是"

    try:
        provider = None
        pid = str(cfg["llm_provider_id"] or "")
        if pid:
            try:
                provider = star.context.get_provider_by_id(pid)
            except Exception:
                provider = None
        if provider is None:
            provider = await star.context.get_using_provider_async()
        if provider is None:
            return None, None
        resp = await asyncio.wait_for(
            provider.text_chat(
                prompt=block,
                system_prompt=_SYS_FOLLOWUP if followup else _SYS,
                session_id=uuid.uuid4().hex,
                persist=False,
            ),
            timeout=float(cfg["timeout_seconds"]),
        )
        out = (resp.completion_text or "").strip()
        verdict = None
        if out.upper().startswith("YES"):
            verdict = True
        elif out.upper().startswith("NO"):
            verdict = False
        alias = None
        m = re.search(r"ALIAS\s*[:：]\s*(.+)", out, re.IGNORECASE)
        if m:
            cand = m.group(1).strip().splitlines()[0].strip()
            if cand and cand not in ("-", "—", "无", "none", "None"):
                alias = cand
        return verdict, alias
    except asyncio.TimeoutError:
        logger.info("[群聊注意] 判定超时，退回概率")
        return None, None
    except Exception:
        logger.exception("[群聊注意] 判定失败，退回概率")
        return None, None


@register("astrbot_group_attention", "dsh", "群聊里判断「是不是在跟我说话」，替代固定概率主动回复", "v0.3.0")
class GroupAttention(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context, config)
        self._last_judge: dict[str, float] = {}
        self._follow: dict[str, int] = {}
        self._patched = _install(self)
        logger.info("[群聊注意] 已接管主动回复判定（patched=%s）", self._patched)

    @filter.on_llm_response()
    async def on_llm_response(self, event, resp) -> None:
        """自己每回完一句，就盯住接下来 N 条。"""
        try:
            cfg = _load_cfg()
            if not cfg.get("enabled", True) or not cfg.get("followup_judge", True):
                return
            if event.get_message_type() != MessageType.GROUP_MESSAGE:
                return
            if not str(getattr(resp, "completion_text", "") or "").strip():
                return
            n = int(cfg.get("followup_window", 3))
            if n > 0:
                self._follow[event.unified_msg_origin] = n
                logger.info("[群聊注意] 已开始跟进窗口 %d 条 | %s", n, event.unified_msg_origin)
        except Exception:
            logger.exception("[群聊注意] 跟进窗口设置失败")


def _install(star: GroupAttention) -> bool:
    try:
        from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
    except Exception:
        logger.exception("[群聊注意] 无法导入 GroupChatContext，插件不生效")
        return False

    if getattr(GroupChatContext, "_short_attention_patched", False):
        return True

    orig = GroupChatContext.need_active_reply

    async def need_active_reply(self, event) -> bool:  # noqa: ANN001
        cfg = _load_cfg()
        if not cfg.get("enabled", True):
            return await orig(self, event)
        try:
            return await _decide(self, event, cfg)
        except Exception:
            logger.exception("[群聊注意] 判定异常，退回内置概率")
            try:
                return await orig(self, event)
            except Exception:
                return False

    async def _decide(self, event, cfg: dict) -> bool:  # noqa: ANN001
        try:
            gc = self.cfg(event)
        except Exception:
            return False
        if not gc["enable_active_reply"]:
            return False
        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            return False
        if event.is_at_or_wake_command:
            return False
        if gc["ar_whitelist"] and (
            event.unified_msg_origin not in gc["ar_whitelist"]
            and (event.get_group_id() and event.get_group_id() not in gc["ar_whitelist"])
        ):
            return False

        text = (event.message_str or "").strip()
        if not text:
            return False

        # 1) 称呼命中（含自学习别名）
        hit = _alias_hit(text, _all_aliases(cfg))
        if hit:
            logger.info("[群聊注意] YES 称呼命中「%s」 | %s", hit, text[:40])
            return True

        # 2) 引用了它的消息
        if await _is_reply_to_self(event):
            logger.info("[群聊注意] YES 引用了它的消息 | %s", text[:40])
            return True

        umo = event.unified_msg_origin

        # 2.5) 只 @ 了别人（没 @ 它）→ 基本是在跟那个人说话，别插嘴
        others, at_self, at_all = _at_targets(event)
        if (
            others
            and not at_self
            and not at_all
            and cfg.get("respect_other_at", True)
        ):
            names = "、".join(n for n, _ in others)[:30]
            logger.info("[群聊注意] NO 只@了别人(%s) | %s", names, text[:30])
            return False

        # 3) 回复后的跟进窗口
        remain = star._follow.get(umo, 0)
        if remain > 0 and cfg.get("followup_judge", True):
            star._follow[umo] = remain - 1
            verdict, alias = await _judge(star, self, event, text, cfg, followup=True)
            if verdict is not None:
                logger.info(
                    "[群聊注意] 跟进判定(剩 %d) %s | %s",
                    remain - 1, "YES" if verdict else "NO", text[:40],
                )
                if verdict and alias:
                    _bump_alias(alias, cfg)
                return verdict

        # 4) 你/您 或 疑问句 → 让模型判
        pron = [p for p in cfg["pronouns"] if p and p in text]
        if (pron or _QUESTION.search(text)) and cfg.get("llm_judge", True):
            now = time.time()
            if now - star._last_judge.get(umo, 0) >= float(cfg["cooldown_seconds"]):
                star._last_judge[umo] = now
                verdict, alias = await _judge(star, self, event, text, cfg)
                if verdict is not None:
                    logger.info("[群聊注意] 判定 %s | %s", "YES" if verdict else "NO", text[:40])
                    if verdict and alias:
                        _bump_alias(alias, cfg)
                    return verdict

        # 5) 兜底概率
        p = float(cfg["fallback_probability"])
        hit_p = random.random() < p
        logger.debug("[群聊注意] 兜底概率 %.2f -> %s", p, hit_p)
        return hit_p

    try:
        GroupChatContext.need_active_reply = need_active_reply
        GroupChatContext._short_attention_patched = True
    except Exception:
        logger.exception("[群聊注意] 打补丁失败")
        return False
    return True
