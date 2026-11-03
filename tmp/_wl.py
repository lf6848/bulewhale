import json
import sys

p = "/opt/astrbot/data/config/astrbot_brain_read_config.json"
c = json.load(open(p, encoding="utf-8"))
who = sys.argv[1] if len(sys.argv) > 1 else "lflove02"
ids = c.get("inject_user_ids") or []
if who == "none":
    c["inject_user_ids"] = [i for i in ids if i != "lflove02"]
else:
    if who not in ids:
        ids.append(who)
    c["inject_user_ids"] = ids
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("whitelist:", c["inject_user_ids"])
