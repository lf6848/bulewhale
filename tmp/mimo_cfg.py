import json, os, shutil, time

MIMO_KEY = os.environ.get("MIMO_API_KEY", "")
if not MIMO_KEY:
    raise SystemExit("MIMO_API_KEY 未配置；未创建备份或修改配置")

P = "/opt/astrbot/data/cmd_config.json"
shutil.copy(P, P + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))

with open(P, encoding="utf-8-sig") as f:
    cfg = json.load(f)

SRC_ID = "mimo-vision-source"
PROV_ID = "mimo-vision"

sources = cfg.setdefault("provider_sources", [])
sources = [s for s in sources if s.get("id") != SRC_ID]
sources.append({
    "id": SRC_ID,
    "provider": "openai",
    "type": "openai_chat_completion",
    "provider_type": "chat_completion",
    "key": [MIMO_KEY],
    "api_base": "https://api.xiaomimimo.com/v1",
    "timeout": 120,
    "proxy": "",
    "custom_headers": {},
})
cfg["provider_sources"] = sources

provs = cfg.setdefault("provider", [])
provs = [p for p in provs if p.get("id") != PROV_ID]
provs.append({
    "id": PROV_ID,
    "enable": True,
    "model": "mimo-v2.6-flash",
    "modalities": ["text", "image"],
    "provider_source_id": SRC_ID,
    "custom_extra_body": {},
})
cfg["provider"] = provs

ar = cfg.setdefault("agent_runner", {}).setdefault("config", {}).setdefault("model", {})
fb = [x for x in ar.get("fallback_provider_ids", []) if x != PROV_ID]
fb.append(PROV_ID)
ar["fallback_provider_ids"] = fb
ar.setdefault("provider_id", "deepseek")

with open(P, "w", encoding="utf-8-sig") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("providers:", [p["id"] + "/" + p["model"] + "/" + ",".join(p.get("modalities", [])) for p in cfg["provider"]])
print("sources:", [s["id"] + "@" + s["api_base"] for s in cfg["provider_sources"]])
print("fallback:", cfg["agent_runner"]["config"]["model"]["fallback_provider_ids"])
