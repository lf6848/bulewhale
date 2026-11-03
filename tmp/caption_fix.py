import json, shutil, time

P = "/opt/astrbot/data/cmd_config.json"
shutil.copy(P, P + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))

with open(P, encoding="utf-8-sig") as f:
    cfg = json.load(f)

ltm = cfg.setdefault("provider_ltm_settings", {})
old = ltm.get("image_caption_provider_id")
ltm["image_caption"] = True
ltm["image_caption_provider_id"] = "mimo-vision"

with open(P, "w", encoding="utf-8-sig") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

provs = {p["id"]: p for p in cfg.get("provider", [])}
print("image_caption_provider_id:", old, "->", ltm["image_caption_provider_id"])
print("providers:", [(rid, p.get("model"), p.get("modalities")) for rid, p in provs.items()])
print("fallback:", cfg.get("agent_runner", {}).get("config", {}).get("model", {}).get("fallback_provider_ids"))
