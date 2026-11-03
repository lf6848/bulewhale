import json
import sqlite3

db = "/AstrBot/data/data_v4.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = c.execute(
    "select id, sender_name, content, created_at from platform_message_history "
    "where user_id like '%GroupMessage%' order by id desc limit 24"
).fetchall()

for rid, name, content, ts in reversed(rows):
    try:
        d = json.loads(content)
    except Exception:
        continue
    segs = d.get("message") or []
    kinds = []
    text = ""
    for s in segs:
        t = s.get("type")
        if t == "plain":
            text += s.get("text", "")
        elif t == "at":
            text += f"@{s.get('name')}({s.get('user_id')})"
        elif t == "reply":
            kinds.append(f"REPLY→{s.get('sender_name')}:{(s.get('text') or '')[:40]}")
        elif t == "image":
            text += "[图]"
        elif t == "face":
            text += "[表情]"
        elif t not in ("plain",):
            kinds.append(t)
    flag = " <<<" if kinds else ""
    print(f"{rid} {ts[:16]} {name}: {text[:70]!r} {'|'.join(kinds)[:80]}{flag}")
