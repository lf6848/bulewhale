# -*- coding: utf-8 -*-
"""桩测试 astrbot_brain_read v0.2：自我注入 / 日期选材 / 主题选材 / 原话不注入 / 幂等 / 白名单。"""
import importlib.util
import json
import os
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def make_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.AstrBotConfig = dict
    api.logger = types.SimpleNamespace(info=lambda *a, **k: None,
                                       warning=lambda *a, **k: None,
                                       error=lambda *a, **k: None)
    ev = types.ModuleType("astrbot.api.event")
    ev.AstrMessageEvent = object

    def on_llm_request():
        def deco(fn):
            fn.__hook__ = True
            return fn

        return deco

    def register(*args, **kwargs):
        def deco(cls):
            return cls

        return deco

    ev.filter = types.SimpleNamespace(on_llm_request=on_llm_request)
    star = types.ModuleType("astrbot.api.star")
    star.Context = object

    class Star:
        def __init__(self, context=None):
            self.context = context

    star.Star = Star
    star.register = register

    sys.modules.update({"astrbot": astrbot, "astrbot.api": api,
                        "astrbot.api.event": ev, "astrbot.api.star": star,
                        "astrbot.api.provider": types.ModuleType("astrbot.api.provider")})
    astrbot.api = api
    api.event = ev
    api.star = star


class Event:
    def __init__(self, text, sid="1034867860", umo="aiocqhttp:FriendMessage:1034867860"):
        self.message_str = text
        self._sid = sid
        self.unified_msg_origin = umo

    def get_sender_id(self):
        return self._sid


class Req:
    def __init__(self, prompt, system_prompt="你是大肥鱼。"):
        self.prompt = prompt
        self.system_prompt = system_prompt


def load_plugin(brain_dir):
    os.environ["BRAIN_DIR"] = brain_dir
    spec = importlib.util.spec_from_file_location("brain_read_main", os.path.join(HERE, "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    make_stubs()
    tmp = os.path.join(HERE, "_stub")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, "diary"), exist_ok=True)
    with open(os.path.join(tmp, "self.md"), "w", encoding="utf-8") as f:
        f.write("【我是谁】\n我是大肥鱼，嘴硬心软。")
    with open(os.path.join(tmp, "diary_index.json"), "w", encoding="utf-8") as f:
        json.dump({"2026-10-27": "一起去吃了水饺。",
                   "2026-10-29": "聊了味觉交互器，战绩账还欠着。"}, f, ensure_ascii=False)
    with open(os.path.join(tmp, "diary", "2026-10-29.md"), "w", encoding="utf-8") as f:
        f.write("【还带着情绪】有点困。\n【今天记得的三件事】味觉器、战绩、作业。")

    mod = load_plugin(tmp)
    P = mod.BrainRead(None, {"inject_user_ids": ["1034867860"]})

    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))

    r = Req("我平时关注哪个战队")
    P._inject(Event("我平时关注哪个战队"), r)
    check("自我档案进入 system_prompt", mod.SELF_MARK in (r.system_prompt or ""))
    check("非时间问句不注入日记", mod.DIARY_MARK not in (r.prompt or ""))

    r2 = Req("昨天那个战绩对比怎么样了")
    P._inject(Event("昨天那个战绩对比怎么样了"), r2)
    p2 = r2.prompt or ""
    check("时间词触发日记注入", mod.DIARY_MARK in p2)
    check("标题用真实日期（昨天没有则退回最近一篇）", "【2026-10-29 的日记】" in p2, p2[:80].replace("\n", " "))

    r3 = Req("你昨天原话是怎么说的")
    P._inject(Event("你昨天原话是怎么说的"), r3)
    check("问原话时不注入日记", mod.DIARY_MARK not in (r3.prompt or ""))

    r4 = Req("之前那个味觉交互器怎么样了")
    P._inject(Event("之前那个味觉交互器怎么样了"), r4)
    p4 = r4.prompt or ""
    check("主题匹配命中相关日期", mod.DIARY_MARK in p4 and "2026-10-29" in p4)

    r5 = Req("上周都干嘛了")
    P._inject(Event("上周都干嘛了"), r5)
    check("上周窗口不报错", isinstance(r5.prompt, str))

    before = r2.prompt
    P._inject(Event("昨天那个战绩对比怎么样了"), r2)
    check("重复调用幂等", r2.prompt == before)

    r6 = Req("昨天咋样")
    P._inject(Event("昨天咋样", sid="999"), r6)
    check("白名单外不注入", mod.SELF_MARK not in (r6.system_prompt or "")
          and mod.DIARY_MARK not in (r6.prompt or ""))

    mod2 = load_plugin(tmp)
    P7 = mod2.BrainRead(None, {"inject_user_ids": ["1034867860"], "enabled": False})
    r7 = Req("昨天咋样")
    P7._inject(Event("昨天咋样"), r7)
    check("enabled=false 时完全不注入", mod2.SELF_MARK not in (r7.system_prompt or ""))

    P8 = mod2.BrainRead(None, {"inject_user_ids": ["1034867860"], "inject_diary": False})
    r8 = Req("昨天咋样")
    P8._inject(Event("昨天咋样"), r8)
    check("inject_diary=false 只注入自我", mod2.SELF_MARK in (r8.system_prompt or "")
          and mod2.DIARY_MARK not in (r8.prompt or ""))

    # 12. 兴趣文件拼进自我块
    ipath = os.path.join(tmp, "interests.md")
    with open(ipath, "w", encoding="utf-8") as f:
        f.write("# 我自己在看的\n\n- 民间硬核DIY（权重 1.0）：喜欢看人用废品做出离谱的东西\n")
    mod.INTERESTS_MD = ipath
    txt = P._self_text()
    check("兴趣拼进自我", "我自己最近在看的" in txt and "民间硬核DIY" in txt,
          txt[-60:].replace("\n", " "))
    P.cfg["inject_interests"] = False
    check("关掉兴趣开关", "我自己最近在看的" not in P._self_text())
    P.cfg["inject_interests"] = True

    print("RESULT", "ALL PASS" if ok else "HAS FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
