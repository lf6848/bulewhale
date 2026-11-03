# -*- coding: utf-8 -*-
"""离线桩测试 astrbot_proactive_v2：不连 AstrBot、不连网。"""

import asyncio
import io
import json
import os
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "_data")
os.makedirs(DATA, exist_ok=True)
os.environ["PROACTIVE_V2_DATA"] = DATA

# ---- 造 astrbot 桩模块 ----
def mod(name, **kw):
    m = types.ModuleType(name)
    for k, v in kw.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Logger:
    def info(self, *a):
        print("  [log]", a[0] % a[1:] if len(a) > 1 else a[0])

    warning = info
    error = info


class _Filter:
    class EventMessageType:
        PRIVATE_MESSAGE = "private"
        GROUP_MESSAGE = "group"
        OTHER_MESSAGE = "other"

    @staticmethod
    def event_message_type(*a, **k):
        def deco(fn):
            return fn
        return deco

    @staticmethod
    def command(*a, **k):
        def deco(fn):
            return fn
        return deco


class Plain:
    def __init__(self, text=""):
        self.text = text


class MessageChain:
    def __init__(self, chain):
        self.chain = chain


class Star:
    def __init__(self, context=None, *a, **k):
        self.context = context


def register(*a, **k):
    def deco(cls):
        return cls
    return deco


mod("astrbot")
mod("astrbot.api", logger=_Logger(), AstrBotConfig=dict, Star=Star, Context=object, register=register)
mod("astrbot.api.event", filter=_Filter, AstrMessageEvent=object)
mod("astrbot.api.message_components", Plain=Plain)
mod("astrbot.api.star", Context=object, Star=Star, register=register)
mod("astrbot.core")
mod("astrbot.core.message")
mod("astrbot.core.message.message_event_result", MessageChain=MessageChain)
sys.modules["astrbot"].api = sys.modules["astrbot.api"]

import main as P  # noqa: E402

# ---- 假 provider ----
class Resp:
    def __init__(self, t):
        self.completion_text = t


class FakeProvider:
    def __init__(self, pick, text, browse=None):
        self.pick = pick
        self.text = text
        self.browse = browse
        self.calls = []

    async def text_chat(self, prompt="", system_prompt="", session_id="", persist=False):
        self.calls.append(system_prompt[:16])
        if "刷热榜" in system_prompt:
            return Resp(self.browse or "")
        if "决定" in system_prompt:
            return Resp(self.pick or "")
        return Resp(self.text)


class FakeCtx:
    def __init__(self, provider):
        self.provider = provider
        self.sent = []

    async def get_using_provider_async(self):
        return self.provider

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain.chain[0].text))
        return True


def make_star(provider):
    s = P.ProactiveV2.__new__(P.ProactiveV2)
    s.cfg = dict(P.DEFAULTS)
    s.cfg.update({"web_enabled": False, "interval_minutes": 120, "own_share_enabled": False})
    s.cfg["targets"] = [{"umo": s.cfg["umo"], "label": "私聊", "kind": "private",
                         "weight": 1, "max_per_day": s.cfg["max_per_day"], "types": None}]
    s._group_active = {}
    s.db = P.DB(os.path.join(DATA, "proactive.db"))
    s.db.c.execute("delete from pending")
    s.db.c.execute("delete from log")
    s.db.c.execute("delete from state")
    s.db.c.commit()
    s.context = FakeCtx(provider)
    s._busy = False
    s._task = None
    s._last_user_at = time.time() - 3 * 3600
    return s


def run(coro):
    return asyncio.run(coro)


ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


pick_json = json.dumps(
    {
        "updates": [{"memory_id": 90, "status": "deferred", "user_words": "等他回时间"}],
        "pick": {"type": "pending", "memory_id": 90, "reason": "他下午去谈了", "angle": "问结果", "focus": "约谈结果"},
        "web": {"need": False, "query": ""},
    },
    ensure_ascii=False,
)

P.Memory.pending_candidates = classmethod(lambda cls, umo, limit=8: [{"id": 90, "type": "event", "text": "与陈老师约谈", "importance": 0.6}])
P.Memory.interests = classmethod(lambda cls, umo, limit=10: [{"id": 30, "type": "preference", "text": "关注天禄", "importance": 0.55}])
P.Memory.recent_dialogue = classmethod(lambda cls, umo, limit=12: [("他", "两点半去找陈老师谈"), ("我", "那你先想好问什么")])

# 1. 频率闸门：刚说过话不发
s = make_star(FakeProvider(pick_json, "谈完说说结果。"))
s._last_user_at = time.time() - 60
okfire, why = s._can_fire()
check("刚聊过不发", okfire is False and "空闲" in why, why)

# 2. 空闲足够则发，且发送一次、记账一次
s = make_star(FakeProvider(pick_json, "两点半那事聊得怎么样，有没有问到你想要的方向？"))
run(s._fire())
check("发送一次", len(s.context.sent) == 1, s.context.sent)
check("日志已记", len(s.db.last_logs(5)) == 1)
check("待办被标记 nudged", s.db.pending_rows()[0]["nudge_count"] == 1, s.db.pending_rows())

# 3. 状态机：deferred 冷却期内，再选同一条会被否决
pick2 = json.dumps(
    {"updates": [], "pick": {"type": "pending", "memory_id": 90, "reason": "还想问", "angle": "催一催"}, "web": {}},
    ensure_ascii=False,
)
s2 = make_star(FakeProvider(pick2, "那事你还没去吧？"))
s2.db.upsert_pending(90, "deferred", "等他回时间")
s2.db.mark_nudged(90)
pick = run(s2._pick(FakeProvider(pick2, "")))
check("deferred 冷却期内否决 pending", pick.get("type") != "pending", pick)
check("否决后改成关心", pick.get("type") == "care", pick)

# 4. 冷却期过了之后允许再提
s2.db.c.execute("update pending set last_nudged_at=? where memory_id=90", (time.time() - 72 * 3600,))
s2.db.c.commit()
pick = run(s2._pick(FakeProvider(pick2, "")))
check("48 小时后允许再提", pick.get("type") == "pending", pick)

# 5. 生成去重：与上次太像会重写
p = FakeProvider(None, "在干嘛呢")
s3 = make_star(p)
s3.db.add_log("care", None, "", "在干嘛呢", False)
text = run(s3._compose(p, {"type": "care", "reason": "", "angle": "", "focus": ""}, ""))
check("雷同时触发重写", len(p.calls) == 2, p.calls)

# 6. 空生成不发
p2 = FakeProvider(json.dumps({"pick": {"type": "care", "memory_id": None}, "web": {}}, ensure_ascii=False), "")
s4 = make_star(p2)
run(s4._fire())
check("空文本不发送", len(s4.context.sent) == 0)

# 7. 自己刷：挑中一条 → 记录兴趣 + 写 interests.md
browse_json = json.dumps({"pick_title": "男子用3000个易拉罐做了一台机器人", "reason": "离谱但真做出来了",
                          "interest": {"topic": "民间硬核DIY", "note": "喜欢看人用废品做出离谱的东西"}}, ensure_ascii=False)
P.browse = lambda cfg: ("抖音 热榜 今天", ["男子用3000个易拉罐做了一台机器人", "某明星官宣恋情"])
p3 = FakeProvider(None, "刚刷到有人拿三千个易拉罐拼了个机器人，离谱，我有点想看他怎么动的。", browse=browse_json)
s5 = make_star(p3)
s5.db.c.execute("delete from own_interests")
s5.db.c.commit()
pick_own, titles, q = run(s5._pick_own(p3))
check("刷到并选中", bool(pick_own) and pick_own["type"] == "own" and pick_own["focus"].startswith("男子"), pick_own)
check("兴趣入库", any(r["topic"] == "民间硬核DIY" for r in s5.db.interests()), s5.db.interests())
check("interests.md 已写", os.path.exists(P.INTERESTS_MD) and "民间硬核DIY" in io.open(P.INTERESTS_MD, encoding="utf-8").read())
check("兴趣权重=1", [r for r in s5.db.interests() if r["topic"] == "民间硬核DIY"][0]["weight"] == 1.0)

# 8. 刷不到就返回 None（外层会回落到普通选题）
P.browse = lambda cfg: ("", [])
pick_none, _, _ = run(s5._pick_own(p3))
check("刷不到返回 None", pick_none is None)

# 9. 自己刷的每日限额计数
s5.db.c.execute("delete from browse_log")
s5.db.c.commit()
for i in range(2):
    s5.db.log_browse("q", [], "标题%d" % i, "r")
check("每天 own 计数", s5.db.own_today() == 2)
check("到限额", s5.db.own_today() >= s5.cfg["own_share_per_day"])

# 10. 我在意的事：从 self.md 解析 + 选中 + 发过就冷却
focus_json = json.dumps({
    "updates": [],
    "pick": {"type": "focus", "focus": "战绩对比", "reason": "拖了几天了，一句话就能问清", "angle": "直接问"},
}, ensure_ascii=False)
p6 = FakeProvider(focus_json, "战绩那事，你翻了没？")
s6 = make_star(p6)
s6._focus_items = lambda: [{"topic": "战绩对比", "since": "2026-10-29"},
                           {"topic": "味觉交互器", "since": "2026-10-29"}]
s6.db.c.execute("delete from focus_log")
s6.db.c.commit()
pick_focus = run(s6._pick(p6))
check("选中在意的事", pick_focus.get("type") == "focus" and pick_focus.get("focus") == "战绩对比", pick_focus)

s6.db.add_focus("战绩对比")
s6.db.focus_set("战绩对比", "asked", bump_asked=True)
pick_cool = run(s6._pick(p6))
check("刚问过、还没回，不追", pick_cool.get("type") == "care", pick_cool)

s6.db.focus_set("战绩对比", "waiting")
pick_wait = run(s6._pick(p6))
check("对方在等结果时不催", pick_wait.get("type") == "care", pick_wait)

s6.db.c.execute("delete from focus_log")
s6.db.c.commit()
s6._focus_items = lambda: [{"topic": "战绩对比", "since": "2026-10-29"}]
s6.db.focus_set("战绩对比", "asked", bump_asked=True)
s6.db.c.execute("update focus_state set asked_at=? where topic='战绩对比'",
                (time.time() - 3 * 3600,))
s6.db.c.commit()
check("90 分钟后仍未回可再问", run(s6._pick(p6)).get("type") == "focus")

s6.db.focus_set("战绩对比", "dropped")
check("已了结的不再提", run(s6._pick(p6)).get("type") == "care")
s6.db.c.execute("delete from focus_state")
s6.db.c.commit()

s6.db.c.execute("delete from focus_log")
s6.db.c.commit()
s6._focus_items = lambda: []
check("对不上号就换 care", run(s6._pick(p6)).get("type") == "care")
s6.db.c.execute("delete from focus_log")
s6.db.c.commit()

# 11. 间隔：指数分布，夹在 [30,120]，均值接近 90
gaps = []
for _ in range(400):
    s6._roll_gap()
    gaps.append(s6._gap_min)
avg = sum(gaps) / len(gaps)
check("间隔在范围内", min(gaps) >= 30 and max(gaps) <= 120, (min(gaps), max(gaps)))
check("间隔均值接近 90", 70 <= avg <= 95, round(avg, 1))
check("有短间隔(<60)", any(g < 60 for g in gaps))

# 12. 多目标：群聊限额与类型限制
s7 = make_star(FakeProvider(pick_json, "群里冒个泡。"))
s7.cfg["targets"] = [
    {"umo": "aiocqhttp:FriendMessage:1034867860", "label": "私聊", "kind": "private", "weight": 1, "max_per_day": 6},
    {"umo": "aiocqhttp:GroupMessage:726921160", "label": "群聊", "kind": "group", "weight": 1,
     "max_per_day": 1, "types": ["interest", "care", "own"]},
]
s7.db.c.execute("delete from log")
s7.db.c.commit()
picked = [s7._choose_target()["kind"] for _ in range(60)]
check("两种目标都会被选中", set(picked) == {"private", "group"}, set(picked))

s7.db.add_log("care", None, "", "群里的一句", False, target="aiocqhttp:GroupMessage:726921160")
s7.db.c.execute("delete from log where target=''")
s7.db.c.commit()
after = [s7._choose_target()["kind"] for _ in range(40)]
check("群聊到上限后只走私聊", set(after) == {"private"}, set(after))

pick_pending = run(s7._pick(FakeProvider(pick_json, "x"), allow_types=["interest", "care", "own"]))
check("群聊不选私事话题", pick_pending.get("type") == "care", pick_pending)

s7.db.c.execute("delete from log")
s7.db.c.commit()

# 13. 群里正在聊的时候不插话
s7._group_active = {"aiocqhttp:GroupMessage:726921160": time.time()}
busy = [s7._choose_target()["kind"] for _ in range(30)]
check("群里刚有人说话时只走私聊", set(busy) == {"private"}, set(busy))
s7._group_active = {}

print("\nRESULT ok=%d fail=%d" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
