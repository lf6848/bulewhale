import json

P = "/AstrBot/data/cmd_config.json"
c = json.load(open(P, encoding="utf-8-sig"))

srcs = {s.get("id"): s for s in c.get("provider_sources", [])}
print("== providers")
for p in c.get("provider", []):
    sid = p.get("provider_source_id")
    s = srcs.get(sid, {})
    key = (s.get("key") or [""])[0]
    print(
        f'  id={p.get("id")} model={p.get("model")} modalities={p.get("modalities")} '
        f'source={sid} api_base={s.get("api_base")} key={key[:8]}...{key[-4:]}'
    )

print("== agent_runner.model")
m = c.get("agent_runner", {}).get("config", {}).get("model", {})
print("  default_provider_id:", m.get("default_provider_id"))
print("  fallback_provider_ids:", m.get("fallback_provider_ids"))

print("== provider_settings")
ps = c.get("provider_settings", {})
for k in ("default_provider_id", "web_search", "websearch_provider", "image_caption"):
    print(f"  {k}:", ps.get(k))

print("== ltm")
print("  image_caption_provider_id:", c.get("provider_ltm_settings", {}).get("image_caption_provider_id"))
