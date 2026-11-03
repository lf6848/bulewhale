# -*- coding: utf-8 -*-
import base64, hashlib, hmac, json, sys, time, urllib.request
cfg = json.loads(open("/opt/astrbot/data/cmd_config.json", encoding="utf-8-sig").read())
secret = cfg["dashboard"]["jwt_secret"]
user = cfg["dashboard"].get("username") or "astrbot"

def b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def jwt():
    h = b64(json.dumps({"alg":"HS256","typ":"JWT"},separators=(",",":")).encode())
    p = b64(json.dumps({"username":user,"exp":int(time.time())+3600},separators=(",",":")).encode())
    s = b64(hmac.new(secret.encode(),("%s.%s"%(h,p)).encode(),hashlib.sha256).digest())
    return "%s.%s.%s"%(h,p,s)

def ask(msg, sid):
    body = json.dumps({"session_id":sid,"message":msg},ensure_ascii=False).encode()
    req = urllib.request.Request("http://127.0.0.1:6185/api/chat/send",data=body,
        headers={"Content-Type":"application/json","Authorization":"Bearer "+jwt()})
    raw = urllib.request.urlopen(req,timeout=180).read().decode("utf-8","ignore")
    parts=[]
    for line in raw.splitlines():
        line=line.strip()
        if not line.startswith("data:"): continue
        try: ev=json.loads(line[5:].strip())
        except Exception: continue
        if ev.get("type")=="plain" and ev.get("streaming"):
            parts.append(str(ev.get("data") or ""))
    return "".join(parts)

q = sys.argv[1]; sid = sys.argv[2]
print("Q:", q)
print("A:", ask(q, sid).replace("\n"," / ")[:600])
