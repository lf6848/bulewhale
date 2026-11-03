import sys
sys.path.insert(0, "/AstrBot/data/plugins")
import astrbot_proactive_v2.main as M
o = M.ProactiveV2.__new__(M.ProactiveV2)
o.cfg = dict(M.DEFAULTS)
print("focus items:", o._focus_items())
import random
gaps = []
for _ in range(200):
    o._roll_gap()
    gaps.append(o._gap_min)
print("gap min/avg/max:", round(min(gaps), 1), round(sum(gaps) / len(gaps), 1), round(max(gaps), 1))
