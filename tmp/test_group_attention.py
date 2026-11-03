"""本地桩测试 group_attention v0.2 的判定链路（不连接服务器）。"""
import asyncio
import os
import sys
import tempfile
import types

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "group_attention_main.py")

# ---------------- 桩模块 ----------------
events = types.ModuleType("astrbot.api.event")


class _Filter:
    def on_llm_response(self):
        def deco(fn):
            return fn
        return deco

    def llm_tool(self, *a, **k):
        def deco(fn):
            return fn
        return deco


events.filter = _Filter()
events.AstrMessageEvent = object

platform = types.ModuleType("astrbot.api.platform")


class MessageType:
    GROUP_MESSAGE = "group"
    FRIEND_MESSAGE = "friend"


platform.MessageType = MessageType


class Star:
    def __init__(self, context=None, config=None):
        self.context = context


star_mod = types.ModuleType("astrbot.api.star")
star_mod.Star = Star
star_mod.Context = object


def register(*a, **k):
    def deco(cls):
        return cls
    return deco


star_mod.register = register

api = types.ModuleType("astrbot.api")


class _Logger:
    def info(self, *a, **k):
        print("  [log.INFO]", a[0] % a[1:] if len(a) > 1 else a[0])

    def debug(self, *a, **k):
        pass

    def exception(self, *a, **k):
        import traceback

        print("  [log.EXC]", a[0])
        traceback.print_exc()


api.logger = _Logger()
api.AstrBotConfig = dict

for name, mod in [
    ("astrbot", types.ModuleType("astrbot")),
    ("astrbot.api", api),
    ("astrbot.api.event", events),
    ("astrbot.api.platform", platform),
    ("astrbot.api.star", star_mod),
]:
    sys.modules.setdefault(name, mod)
sys.modules["astrbot"].api = api
api.event = events
api.platform = platform
api.star = star_mod

# 假的 group_chat_context
gcc = types.ModuleType("astrbot.builtin_stars.astrbot.group_chat_context")


class GroupChatContext:
    def __init__(self):
        self.raw_records = {"aiocqhttp:GroupMessage:726921160": ["甲: 大肥鱼在吗", "乙: 你说呢"]}

    def cfg(self, event):
        return {
            "enable_active_reply": True,
            "ar_whitelist": [],
            "ar_possibility": 0.1,
        }

    async def need_active_reply(self, event):
        return "ORIG"


gcc.GroupChatContext = GroupChatContext
for n in ("astrbot.builtin_stars", "astrbot.builtin_stars.astrbot"):
    sys.modules.setdefault(n, types.ModuleType(n))
sys.modules["astrbot.builtin_stars.astrbot.group_chat_context"] = gcc

# ---------------- 加载被测插件 ----------------
ns = {"__name__": "ga_under_test", "__file__": SRC}
with open(SRC, encoding="utf-8") as f:
    exec(compile(f.read(), SRC, "exec"), ns)

GroupAttention = ns["GroupAttention"]

tmpdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ga_tmp")
os.makedirs(tmpdir, exist_ok=True)
ns["CONFIG_PATH"] = os.path.join(tmpdir, "cfg.json")
ns["LEARNED_PATH"] = os.path.join(tmpdir, "learned.json")

import json
with open(ns["CONFIG_PATH"], "w", encoding="utf-8") as f:
    json.dump(ns["DEFAULTS"], f, ensure_ascii=False)


# ---------------- 假 event / provider ----------------
class Seg:
    pass


class Msg:
    def __init__(self, text, self_id="3952927705", msg_type="group", reply_to=None):
        self.message_str = text
        self.message = []
        self.self_id = self_id
        self._mt = msg_type
        self.unified_msg_origin = "aiocqhttp:GroupMessage:726921160"

    def get_message_type(self):
        return self._mt

    def get_sender_name(self):
        return "大帅哥"

    def get_sender_id(self):
        return "1497575193"

    def get_group_id(self):
        return "726921160"

    @property
    def is_at_or_wake_command(self):
        return False


class Resp:
    completion_text = "我在呢"


class Provider:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = []

    async def text_chat(self, prompt, system_prompt=None, session_id=None, persist=False):
        self.calls.append(system_prompt[:12])
        r = types.SimpleNamespace()
        r.completion_text = self.verdict
        return r


class Ctx:
    def __init__(self, provider):
        self.raw_records = {"aiocqhttp:GroupMessage:726921160": ["甲: 大肥鱼在吗", "乙: 你说呢"]}
        self._p = provider

    async def get_using_provider_async(self):
        return self._p

    def get_provider_by_id(self, pid):
        return None


async def main():
    prov = Provider("NO\nALIAS: -")
    plugin = GroupAttention.__new__(GroupAttention)
    plugin.context = Ctx(prov)
    plugin._last_judge = {}
    plugin._follow = {}
    patched = ns["_install"](plugin)
    print("patched:", patched, "| need_active_reply =", GroupChatContext.need_active_reply.__name__)

    gc = GroupChatContext()
    cases = [
        ("大肥鱼出来冒个泡", True, "别名直命中"),
        ("ds 你觉得呢", True, "短别名 ds"),
        ("dsh 这个工具咋样", None, "不应被 ds 误命中"),
        ("你会不会后空翻", True, "你 → 让模型判 YES"),
        ("啥时候打", False, "疑问句 → 模型判 NO"),
        ("哈哈哈哈", False, "无关键词 → 兜底 5%"),
    ]
    for text, expect, why in cases:
        if text == "你会不会后空翻":
            prov.verdict = "YES\nALIAS: 大肥鱼"
        elif text == "ds 你觉得呢":
            prov.verdict = "YES\nALIAS: -"
        else:
            prov.verdict = "NO\nALIAS: -"
        plugin._last_judge.clear()
        got = await GroupChatContext().need_active_reply(Msg(text))
        mark = "OK" if expect is not None and got == expect else ("skip" if expect is None else "FAIL")
        print(f"  {mark:4} {text!r:22} -> {got}  ({why})")

    # 跟进窗口：模拟 bot 刚回复过
    plugin._follow["aiocqhttp:GroupMessage:726921160"] = 3
    prov.verdict = "YES\nALIAS: 肥鱼"
    got = await GroupChatContext().need_active_reply(Msg("那你说说看"))
    print(f"  跟进 第1条 -> {got}, 剩 {plugin._follow['aiocqhttp:GroupMessage:726921160']}")
    print("  已学别名:", ns["_load_learned"]())

    # on_llm_response 开启跟进窗口
    plugin._follow.clear()
    await plugin.on_llm_response(Msg("x"), Resp())
    print("  on_llm_response 后窗口:", plugin._follow)

    # 别名自学习：同一个新称呼出现两次后转正
    plugin._follow.clear()
    plugin._last_judge.clear()
    prov.verdict = "YES" + chr(10) + "ALIAS: 肥鱼酱"
    for _ in range(2):
        plugin._follow["aiocqhttp:GroupMessage:726921160"] = 2
        await GroupChatContext().need_active_reply(Msg("接着说"))
    learned = ns["_load_learned"]()
    print("  学习计数:", learned)
    print("  转正后是否进别名表:", "肥鱼酱" in ns["_all_aliases"](ns["_load_cfg"]()))


asyncio.run(main())
