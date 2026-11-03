import sys, json
sys.path.insert(0, "/AstrBot/data/plugins")
import astrbot_proactive_v2.main as M
o = M.ProactiveV2.__new__(M.ProactiveV2)
with open("/AstrBot/data/config/astrbot_proactive_v2_config.json", encoding="utf-8") as f:
    o.cfg = json.load(f)
for t in o._targets():
    print("target:", t["label"], t["kind"], t["umo"], "w=%s" % t["weight"], "cap=%s" % t["max_per_day"], "types=%s" % t["types"])
cnt = {}
for _ in range(400):
    t = o._choose_target()
    cnt[t["kind"]] = cnt.get(t["kind"], 0) + 1
print("weighted pick over 400:", cnt)
