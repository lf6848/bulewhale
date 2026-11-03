# -*- coding: utf-8 -*-
"""遗忘树 v2 影子插件：只计算、只写影子表，绝不改线上状态、绝不注入。

开关全部来自 /AstrBot/data/config/astrbot_memory_shadow_config.json（热加载）。
默认：shadow_v2=true, read_path_v2=false, write_path_v2=false, maintain_v2=false
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .engine import DEFAULTS, ShadowEngine

CONFIG_PATH = "/AstrBot/data/config/astrbot_memory_shadow_config.json"
DB_PATH = "/AstrBot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"

MARK = "<v2_memory>"


@register("astrbot_memory_shadow", "dsh", "遗忘树 v2 影子计算（只写影子表）", "v0.1.0")
class MemoryShadow(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._cfg: dict = dict(DEFAULTS)
        self._mtime = 0.0
        self._engine: ShadowEngine | None = None
        self._load_cfg(force=True)
        logger.info("[影子] 已加载，shadow=%s read_v2=%s write_v2=%s maintain=%s",
                    self._cfg["shadow_v2"], self._cfg["read_path_v2"],
                    self._cfg["write_path_v2"], self._cfg["maintain_v2"])

    def _load_cfg(self, force: bool = False) -> None:
        try:
            st = os.stat(CONFIG_PATH)
        except OSError:
            if force:
                self._engine = ShadowEngine(DB_PATH, self._cfg)
            return
        if not force and st.st_mtime == self._mtime:
            return
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                user_cfg = json.load(f)
            cfg = dict(DEFAULTS)
            cfg.update({k: v for k, v in user_cfg.items() if k in DEFAULTS})
            self._cfg = cfg
            self._mtime = st.st_mtime
            self._engine = ShadowEngine(DB_PATH, cfg)
            logger.info("[影子] 配置已加载 shadow=%s", cfg["shadow_v2"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[影子] 配置读取失败，沿用旧配置：%s", exc)

    def _whitelist(self) -> set[str]:
        ids = self._cfg.get("inject_user_ids") or []
        return {str(x) for x in ids}

    def _build_block(self, items: list[dict]) -> str:
        lines = []
        for i in items:
            c = (i.get("content") or "").strip()
            if c:
                lines.append("- " + c)
        if not lines:
            return ""
        body = "\n".join(lines)[: int(self._cfg.get("inject_max_chars") or 400)]
        return (f"\n\n{MARK}\n（这些是你早就记得的、关于对方的事，来自过去几天和对方的相处，"
                f"不是这一轮对话里刚出现的内容。相关时直接当成你自己的记忆来用；"
                f"不要说「你刚说的」「你之前提到过」，也不要声称自己\"记录了\"这些事。）\n{body}\n</v2_memory>")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        # 绝不影响请求：只做计算与影子落盘
        if not self._cfg.get("shadow_v2"):
            return
        try:
            self._load_cfg()
            text = (event.message_str or "").strip()
            user_id = str(event.get_sender_id() or "")
            if not user_id:
                return
            umo = str(event.unified_msg_origin or "")
            engine = self._engine or ShadowEngine(DB_PATH, self._cfg)
            res = None
            last_exc: Exception | None = None
            # 数据库被写锁占用是瞬时的：给一次重试，仍失败就放弃本轮
            for attempt in range(2):
                try:
                    res = await asyncio.to_thread(
                        engine.run, user_id=user_id, scope=umo, text=text, umo=umo, write=True)
                    break
                except sqlite3.OperationalError as exc:
                    last_exc = exc
                    self._engine = None  # 下一轮重建连接
                    if attempt == 0:
                        await asyncio.sleep(0.8)
                        engine = ShadowEngine(DB_PATH, self._cfg)
            if res is None:
                raise last_exc or RuntimeError("shadow run failed")
            logger.info("[影子] mode=%s attrs=%s cand=%d inj=%d ids=%s tok=%d %s",
                        res["mode"], ",".join(res["attrs"]) or "-", res["candidates"],
                        len(res["injected"]), [i["id"] for i in res["injected"]],
                        res["tokens"], ";".join(res["notes"]))

            # ---- 灰度注入：仅 read_path_v2 打开 + 用户在受控名单内 ----
            injected_block = ""
            if self._cfg.get("read_path_v2") and user_id in self._whitelist():
                injected_block = self._build_block(res["injected"])
                if injected_block:
                    prompt = getattr(req, "prompt", "") or ""
                    if MARK not in prompt:
                        req.prompt = prompt + injected_block
                        logger.warning("[影子] 已注入 %d 条（read_path_v2 灰度）：ids=%s chars=%d",
                                       len(res["injected"]),
                                       [i["id"] for i in res["injected"]], len(injected_block))

            # 泄漏探针：read_v2 关闭时必须为 False；灰度开启时只报告（预期 True）
            try:
                prompt2 = getattr(req, "prompt", "") or ""
                leak = any((i.get("content") or "")[:12] in prompt2 for i in res["injected"])
                logger.info("[影子] 泄漏检查 leak=%s plen=%d n_inj=%d read_v2=%s",
                            leak, len(prompt2), len(res["injected"]),
                            bool(self._cfg.get("read_path_v2")))
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[影子] 计算失败（已忽略）：%s", exc)
