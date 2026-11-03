#!/usr/bin/env python3
"""Replace SnowLuma wsClients entry with the correct schema (url/role based)."""
import json, subprocess, io

def run(*a):
    return subprocess.run(a, capture_output=True, text=True)

run("docker", "stop", "snowluma")
run("docker", "cp", "snowluma:/app/data/config/onebot.json", "/tmp/onebot.json")
cfg = json.load(io.open("/tmp/onebot.json", encoding="utf-8"))
nets = cfg["networks"]
nets["wsClients"] = [{
    "name": "wsclient-astrbot",
    "url": "ws://astrbot:6199/ws",
    "role": "Universal",
    "reconnectIntervalMs": 5000,
    "messageFormat": "array",
    "reportSelfMessage": False,
}]
json.dump(cfg, io.open("/tmp/onebot.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(json.dumps(nets["wsClients"], ensure_ascii=False))
r = run("docker", "cp", "/tmp/onebot.json", "snowluma:/app/data/config/onebot.json")
print("cp:", r.returncode, r.stderr.strip())
run("docker", "start", "snowluma")
