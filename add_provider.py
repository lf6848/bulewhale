#!/usr/bin/env python3
"""Add a DeepSeek provider to AstrBot config (host-side, container stopped)."""
import io, json, os, subprocess

PATH = "/opt/astrbot/data/cmd_config.json"
KEY = os.environ.get("DEEPSEEK_API_KEY", "")

if not KEY:
    raise SystemExit("DEEPSEEK_API_KEY 未配置；未对容器或配置做任何改动")

subprocess.run(["docker", "stop", "astrbot"], capture_output=True)

cfg = json.load(io.open(PATH, encoding="utf-8-sig"))
entry = {
    "id": "deepseek",
    "provider": "openai",
    "type": "openai_chat_completion",
    "provider_type": "chat_completion",
    "enable": True,
    "key": [KEY],
    "api_base": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "timeout": 120,
    "proxy": "",
    "custom_headers": {},
    "modalities": ["text"],
}
providers = [p for p in (cfg.get("provider") or []) if p.get("id") != "deepseek"]
providers.append(entry)
cfg["provider"] = providers
cfg.setdefault("provider_settings", {})["provider_pool"] = ["*"]

with io.open(PATH, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print("providers:", [(p.get("id"), p.get("model")) for p in providers])
subprocess.run(["docker", "start", "astrbot"], check=False)
