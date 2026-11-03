#!/usr/bin/env python3
"""Wire SnowLuma (OneBot WS client) <-> AstrBot (aiocqhttp reverse-WS server)."""
import json, shutil, subprocess, io, sys

def run(*a, **kw):
    return subprocess.run(a, capture_output=True, text=True, **kw)

# ---------- SnowLuma: add wsClient pointing at AstrBot ----------
run("docker", "cp", "snowluma:/app/data/config/onebot.json", "/tmp/onebot.json")
cfg = json.load(io.open("/tmp/onebot.json", encoding="utf-8"))
nets = cfg.setdefault("networks", {})
clients = nets.setdefault("wsClients", [])
entry = {
    "name": "astrbot",
    "host": "astrbot",
    "port": 6199,
    "path": "/ws",
    "accessToken": "",
    "messageFormat": "array",
    "reportSelfMessage": False,
    "reconnectIntervalMs": 5000,
}
clients = [c for c in clients if c.get("name") != "astrbot"] + [entry]
nets["wsClients"] = clients
json.dump(cfg, io.open("/tmp/onebot.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("snowluma wsClients:", json.dumps(nets["wsClients"], ensure_ascii=False))

run("docker", "stop", "snowluma")
r = run("docker", "cp", "/tmp/onebot.json", "snowluma:/app/data/config/onebot.json")
print("cp back:", r.returncode, r.stderr.strip())
run("docker", "start", "snowluma")

# ---------- AstrBot: add aiocqhttp platform config ----------
script = r'''
import json, io, shutil
p = "/AstrBot/data/cmd_config.json"
shutil.copy(p, p + ".bak")
d = json.load(io.open(p, encoding="utf-8-sig"))
entry = {
    "id": "aiocqhttp",
    "type": "aiocqhttp",
    "enable": True,
    "ws_reverse_host": "0.0.0.0",
    "ws_reverse_port": 6199,
    "ws_reverse_token": "",
}
d["platform"] = [entry]
with io.open(p, "w", encoding="utf-8-sig") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print("astrbot platform:", json.dumps(d["platform"], ensure_ascii=False))
'''
r = run("docker", "exec", "-i", "astrbot", "python", "-", input=script)
print(r.stdout.strip())
print("ERR:", r.stderr.strip()[:800])
