# -*- coding: utf-8 -*-
"""跑 4 次真实 _fire（不发 QQ），看 token 与「说不说」的比例。"""
import asyncio
import importlib.util
import json
import urllib.request

PLUG = "/AstrBot/data/plugins/astrbot_proactive_v2/main.py"
CFG = "/AstrBot/data/config/astrbot_proactive_v2_config.json"
CC = "/AstrBot/data/cmd_config.json"

cc = json.loads(open(CC, encoding="utf-8-sig").read())
prov = [p for p in cc["provider"] if p["id"] == "deepseek"][0]
src = [s for s in cc["provider_sources"] if s["id"] == prov["provider_source_id"]][0]
KEY, BASE = src["key"][0], src["api_base"].rstrip("/")
MODEL = prov.get("model") or "deepseek-chat"


class Resp:
    def __init__(self, text, usage):
        self.completion_text = text
        self.usage = usage


class Provider:
    async def text_chat(self, prompt="", system_prompt="", session_id="", persist=False, **kw):
        payload = {"model": MODEL,
                   "messages": [{"role": "system", "content": system_prompt or "你是大肥鱼。"},
                                {"role": "user", "content": prompt}],
                   "temperature": 1.0, "max_tokens": 500}
        req = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + KEY})
        data = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
        return Resp(data["choices"][0]["message"]["content"], data.get("usage") or {})


class Ctx:
    def __init__(self):
        self.sent = []

    async def get_using_provider_async(self):
        return Provider()

    async def send_message(self, umo, chain):
        self.sent.append(str(chain))


def load():
    spec = importlib.util.spec_from_file_location("pv2_m", PLUG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


async def one(mod):
    star = mod.ProactiveV2.__new__(mod.ProactiveV2)
    star.cfg = dict(mod.DEFAULTS)
    star.cfg.update({k: v for k, v in json.loads(open(CFG, encoding="utf-8").read()).items()
                     if k in mod.DEFAULTS})
    star.db = mod.DB()
    star.context = Ctx()
    star._busy = False
    star._task = None
    star._last_user_at = 0
    star._tok = {"p": 0, "c": 0}
    await star._fire(force_own=True)
    return star._tok["p"] + star._tok["c"], bool(star.context.sent)


def main():
    mod = load()
    tot, said = 0, 0
    for i in range(4):
        t, s = asyncio.run(one(mod))
        tot += t
        said += 1 if s else 0
        print("  run%d token=%d 发出=%s" % (i + 1, t, s))
    print("AVG=%.0f said=%d/4" % (tot / 4.0, said))


main()
