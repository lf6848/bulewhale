import asyncio
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

    warning = error = exception


class Star:
    def __init__(self, context=None, config=None):
        self.context = context


def register(*a, **k):
    def deco(cls):
        return cls

    return deco


class _Filter:
    def on_llm_request(self, *a, **k):
        def deco(fn):
            return fn

        return deco


stub("astrbot")
stub("astrbot.api", logger=_Logger(), AstrBotConfig=dict)
stub("astrbot.api.event", filter=_Filter())
stub("astrbot.api.star", Context=object, Star=Star, register=register)

src = open("tmp/quote_focus_main.py", encoding="utf-8").read()
mod = types.ModuleType("qf")
exec(compile(src, "quote_focus_main.py", "exec"), mod.__dict__)


class At:
    def __init__(self, qq, name=""):
        self.qq, self.name = qq, name


class Reply:
    def __init__(self, sender_nickname="", message_str="", sender_id=""):
        self.sender_nickname = sender_nickname
        self.message_str = message_str
        self.sender_id = sender_id
        self.chain = []


class Plain:
    def __init__(self, text):
        self.text = text


class MO:
    def __init__(self, segs, self_id="3952927705"):
        self.message = segs
        self.self_id = self_id


class Ev:
    def __init__(self, segs, self_id="3952927705"):
        self.message_obj = MO(segs, self_id)


class Req:
    def __init__(self, prompt):
        self.prompt = prompt
        self.extra_user_content_parts = []


cases = [
    ("普通引用", [Reply("大帅哥", " @大肥鱼(3952927705) 再叫一句我听听", "1497575193"), Plain("尼玛")], "尼玛"),
    ("引用自己", [Reply("大肥鱼", "卡三张木兰算什么", "3952927705"), Plain("你会不会玩")], "你会不会玩"),
    ("引用无文字", [Reply("Sawako", "", "1034867860"), Plain("？")], "？"),
    ("无引用", [Plain("今天吃啥")], "今天吃啥"),
]


async def run():
    plugin = mod.QuoteFocus(object())
    for label, segs, prompt in cases:
        req = Req(prompt)
        await plugin.on_llm_request(Ev(segs), req)
        print(f"--- {label}")
        print(req.prompt)
        print()

    # 二次调用应幂等
    req = Req("hi")
    segs = [Reply("大帅哥", "原话", "1497575193"), Plain("hi")]
    ev = Ev(segs)
    await plugin.on_llm_request(ev, req)
    first = req.prompt
    await plugin.on_llm_request(ev, req)
    print("idempotent:", first == req.prompt)


asyncio.run(run())
