"""离线验证 short_recall 的时间窗 + 关键词选择逻辑（只读副本，不碰生产库）。"""
import asyncio, json, shutil, sqlite3, sys, types
from datetime import datetime, timedelta, timezone

SRC = "/opt/astrbot/data/data_v4.db"
DST = "/tmp/hist_copy.db"
shutil.copy(SRC, DST)

pkgs = ["astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.provider", "astrbot.api.star"]
for name in pkgs:
    sys.modules[name] = types.ModuleType(name)
    sys.modules[name].__path__ = []

class _Logger:
    def info(self, *a, **k): print("[I]", *a)
    def warning(self, *a, **k): print("[W]", *a)
    def exception(self, *a, **k): print("[E]", *a)

top = sys.modules["astrbot"]
api = sys.modules["astrbot.api"]
top.api = api
top.AstrBotConfig = dict
top.logger = _Logger()
api.AstrBotConfig = dict
api.logger = _Logger()

ev = sys.modules["astrbot.api.event"]
class AstrMessageEvent: ...
def on_llm_request(*a, **k):
    def deco(fn): return fn
    return deco
ev.AstrMessageEvent = AstrMessageEvent
ev.filter = types.SimpleNamespace(on_llm_request=on_llm_request)

pv = sys.modules["astrbot.api.provider"]
class ProviderRequest: ...
pv.ProviderRequest = ProviderRequest
pv.LLMResponse = object

st = sys.modules["astrbot.api.star"]
class Context: ...
class Star:
    def __init__(self, context=None, config=None): ...
def register(*a, **k):
    def deco(cls): return cls
    return deco
st.Context = Context
st.Star = Star
st.register = register

mod = types.ModuleType("short_recall")
src = open("/opt/astrbot/data/plugins/astrbot_short_recall/main.py", encoding="utf-8").read()
exec(compile(src, "main.py", "exec"), mod.__dict__)
mod.DB_PATH = DST

now = datetime.now(mod.TZ)
print("本地现在:", now.strftime("%Y-%m-%d %H:%M"), "| UTC:", datetime.now(timezone.utc).strftime("%H:%M"))
db = mod.ShortRecallDB(DST)
sess = db.sessions_of("1034867860")
print("该用户参与会话:", sess)

for query in ["昨天我说了什么", "我那个宠物小鸡你还记得吗", "刚才聊到哪了", "前几天群里说过什么", "帮我把这段改写成英文"]:
    win = mod._resolve_window(query, now)
    obj = mod.ShortRecall.__new__(mod.ShortRecall)
    obj.cfg = dict(mod.DEFAULTS)
    obj.db = db
    print("\n===== 提问:", query)
    print("窗口:", None if not win else (win[0].strftime("%m-%d %H:%M"), win[1].strftime("%m-%d %H:%M"), win[2]))
    if not win:
        print("→ 不注入（无时间意图）")
        continue
    pack, picked, label = asyncio.run(obj._build(query, "1034867860", win, obj.cfg["max_items"], obj.cfg["max_tokens"]))
    print(f"命中「{label}」注入 {len(picked)} 条 / {len(pack)} chars")
    print(pack or "(空)")
