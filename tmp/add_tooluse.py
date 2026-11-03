import json
import shutil
import time

P = "/opt/astrbot/data/cmd_config.json"
shutil.copy(P, P + ".bak-mod-" + time.strftime("%Y%m%d-%H%M%S"))
c = json.load(open(P, encoding="utf-8-sig"))

changed = []
for p in c.get("provider", []):
    if p.get("id") == "deepseek":
        mods = p.get("modalities") or ["text"]
        if "tool_use" not in mods:
            mods = list(mods) + ["tool_use"]
            p["modalities"] = mods
            changed.append(("deepseek", mods))
    if p.get("id") == "mimo-vision":
        mods = p.get("modalities") or ["text", "image"]
        if "tool_use" not in mods:
            p["modalities"] = list(mods) + ["tool_use"]
            changed.append(("mimo-vision", p["modalities"]))

json.dump(c, open(P, "w", encoding="utf-8-sig"), ensure_ascii=False, indent=2)
print("changed:", changed)
for p in c.get("provider", []):
    print(p.get("id"), p.get("model"), p.get("modalities"))
