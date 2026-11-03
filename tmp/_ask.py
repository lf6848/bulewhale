# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.request

CC = "/opt/astrbot/data/cmd_config.json"
cfg = json.loads(open(CC, encoding="utf-8-sig").read())
secret = cfg["dashboard"]["jwt_secret"]
user = cfg["dashboard"].get("username") or "astrbot"
BASE = "http://127.0.0.1:6185"


def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwt():
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64(json.dumps({"username": user, "exp": int(time.time()) + 3600},
                          separators=(",", ":")).encode())
    sig = b64(hmac.new(secret.encode(), ("%s.%s" % (head, body)).encode(), hashlib.sha256).digest())
    return "%s.%s.%s" % (head, body, sig)


def ask(msg, sid):
    body = json.dumps({"session_id": sid, "message": msg}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE + "/api/chat/send", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + jwt()})
    raw = urllib.request.urlopen(req, timeout=180).read().decode("utf-8", "ignore")
    out = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            out.append(line[5:].strip())
    text = "\n".join(out) if out else raw
    return text


msg = sys.argv[1]
sid = sys.argv[2] if len(sys.argv) > 2 else "qa%d" % int(time.time())
print(ask(msg, sid)[:1200])
