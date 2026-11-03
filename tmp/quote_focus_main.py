"""astrbot_quote_focus —— 让模型真正"看到并注意到"QQ 引用消息

AstrBot 原生会把被引用的消息拼成一段 `<Quoted Message>...</Quoted Message>`
放在用户正文【后面】（`extra_user_content_parts`），模型经常把它当背景资料忽略。

本插件在 on_llm_request 时把被引用的内容【重排到正文前面】，并明确标注
"谁引用了谁、引用的是不是机器人自己的话"，再附一句"先看懂引用再回答"的提醒。
不改任何核心文件，也不删除原生那段（避免被重新采集）。

配置：/AstrBot/data/config/astrbot_quote_focus_config.json（热加载）
"""

from __future__ import annotations

import json
import os

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register

CONFIG_PATH = "/AstrBot/data/config/astrbot_quote_focus_config.json"

DEFAULTS = {
    "enabled": True,
    "max_quote_chars": 240,
    "hint": True,          # 在引用块后加一句"先看懂引用"
    "self_mark": True,     # 引用的是机器人自己的话时，特别标注
}

MARK = "【我引用了"


def _load_cfg() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception("[引用加强] 读取配置失败，使用默认值")
    return cfg


def _find_quote(event):
    for seg in getattr(event.message_obj, "message", []) or []:
        if type(seg).__name__ == "Reply":
            return seg
    return None


def _quote_text(seg) -> str:
    body = str(getattr(seg, "message_str", "") or "").strip()
    if body:
        return body
    chain = getattr(seg, "chain", None) or []
    out = []
    for c in chain:
        name = type(c).__name__
        if name == "Plain":
            out.append(str(getattr(c, "text", "") or ""))
        elif name == "At":
            qq = str(getattr(c, "qq", "") or "")
            nm = str(getattr(c, "name", "") or qq)
            out.append(f" @{nm}({qq}) ")
        elif name == "Image":
            out.append("[图片]")
        elif name == "Face":
            out.append("[表情]")
    return "".join(out).strip()


def _self_info(event) -> tuple[str, str]:
    me = str(getattr(event.message_obj, "self_id", "") or "")
    name = ""
    for seg in getattr(event.message_obj, "message", []) or []:
        if type(seg).__name__ == "At" and str(getattr(seg, "qq", "") or "") == me and me:
            name = str(getattr(seg, "name", "") or "")
            break
    return me, name


@register("astrbot_quote_focus", "dsh", "把 QQ 引用消息重排到正文前面，让模型真的看引用内容", "v0.1.0")
class QuoteFocus(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context, config)
        logger.info("[引用加强] 已加载")

    @filter.on_llm_request()
    async def on_llm_request(self, event, req) -> None:  # noqa: ANN001
        try:
            cfg = _load_cfg()
            if not cfg["enabled"]:
                return
            prompt = str(getattr(req, "prompt", "") or "")
            if prompt.lstrip().startswith(MARK):
                return  # 已经处理过

            quote = _find_quote(event)
            if quote is None:
                return

            body = _quote_text(quote)[: int(cfg["max_quote_chars"])]
            who = str(getattr(quote, "sender_nickname", "") or "").strip() or "某人"

            me, _ = _self_info(event)
            qq = str(getattr(quote, "sender_id", "") or "")
            is_self = bool(me) and qq == me

            if is_self and cfg["self_mark"]:
                head = f"{MARK}你自己（{who}）刚才说的这条消息】"
            else:
                head = f"{MARK}{who}的一条消息】"

            block = [head]
            if body:
                block.append(body)
            else:
                block.append("（这条引用里没有文字，可能是图片或表情）")
            block.append("【我说的】")

            new_prompt = "\n".join(block) + "\n" + prompt
            if cfg["hint"]:
                new_prompt += (
                    "\n\n（提示：上面那段是这条消息引用/回复的原内容，"
                    "回答前先看懂它，别当背景噪音忽略。）"
                )

            req.prompt = new_prompt
            logger.info(
                "[引用加强] 重排引用 sender=%s self=%s len=%d",
                who, is_self, len(body),
            )
        except Exception:
            logger.exception("[引用加强] 处理引用失败（已忽略，不影响正常回复）")
