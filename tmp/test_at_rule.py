import sys
import types


def stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Logger:
    def info(self, *a, **k):
        print("[log]", a[0] % a[1:] if len(a) > 1 else a[0])

    def debug(self, *a, **k):
        pass

    def exception(self, *a, **k):
        print("[err]", a)

    warning = exception
    error = exception


class MessageType:
    GROUP_MESSAGE = "group"
    FRIEND_MESSAGE = "friend"


class Star:
    def __init__(self, context=None, config=None):
        self.context = context


class Context:
    pass


def register(*a, **k):
    def deco(cls):
        return cls

    return deco


class _Filter:
    def on_llm_response(self, *a, **k):
        def deco(fn):
            return fn

        return deco

    def llm_tool(self, *a, **k):
        def deco(fn):
            return fn

        return deco


stub("astrbot")
stub("astrbot.api", logger=_Logger(), AstrBotConfig=dict)
stub("astrbot.api.event", filter=_Filter())
stub("astrbot.api.platform", MessageType=MessageType)
stub("astrbot.api.star", Context=Context, Star=Star, register=register)

src = open("tmp/group_attention_main.py", encoding="utf-8").read()
mod = types.ModuleType("ga")
mod.__dict__["__name__"] = "ga"
exec(compile(src, "group_attention_main.py", "exec"), mod.__dict__)


class At:
    def __init__(self, qq, name=""):
        self.qq, self.name = qq, name


class Reply:
    def __init__(self, sender_nickname="", message_str="", mid=1):
        self.sender_nickname, self.message_str, self.id = sender_nickname, message_str, mid


class Plain:
    def __init__(self, text):
        self.text = text


class MO:
    def __init__(self, segs, self_id="3952927705"):
        self.message = segs
        self.self_id = self_id


class Ev:
    def __init__(self, segs, text, at_wake=False, umo="aiocqhttp:GroupMessage:1", self_id="3952927705"):
        self.message_obj = MO(segs, self_id)
        self.message_str = text
        self.is_at_or_wake_command = at_wake
        self.unified_msg_origin = umo

    def get_message_type(self):
        return MessageType.GROUP_MESSAGE

    def get_group_id(self):
        return "726921160"

    def get_sender_name(self):
        return "Sawako"

    def get_sender_id(self):
        return "1034867860"


cases = [
    ("只@别人", [At("674289348", "普通网友"), Plain("拉个尿")], " @普通网友(674289348) 拉个尿", False),
    ("@别人+你", [At("674289348", "普通网友"), Plain("你觉得呢")], " @普通网友(674289348) 你觉得呢", False),
    ("@全体", [At("all", "全体成员"), Plain("开会了")], " @全体成员 开会了", True),
]

ga = mod.GroupAttention(Context())
cfg = dict(mod.DEFAULTS)

for label, segs, text, expect_others in cases:
    ev = Ev(segs, text)
    others, at_self, at_all = mod._at_targets(ev)
    print(f"{label}: others={others} at_self={at_self} at_all={at_all}")

print("quote:", mod._quote_info(Ev([Reply("大帅哥", " @大肥鱼(3952927705) 再叫一句我听听"), Plain("尼玛")], "尼玛")))

import asyncio


class FakeGroupChatContext:
    def cfg(self, event):
        return {"enable_active_reply": True, "ar_whitelist": []}

    async def need_active_reply(self, event):
        return False  # 内置：永不主动


stub("astrbot.builtin_stars")
stub("astrbot.builtin_stars.astrbot")
stub("astrbot.builtin_stars.astrbot.group_chat_context", GroupChatContext=FakeGroupChatContext)


async def run():
    star = mod.GroupAttention(Context())
    ok = mod._install(star)
    print("patched:", ok)
    for label, segs, text, _ in cases:
        ev = Ev(segs, text)
        got = await FakeGroupChatContext.need_active_reply(FakeGroupChatContext(), ev)
        print(f"decide[{label}] => {got}")


asyncio.run(run())
