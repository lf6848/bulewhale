import json
import sqlite3

db = "/AstrBot/data/data_v4.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = c.execute(
    "select id, sender_name, content, created_at from platform_message_history "
    "where user_id like '%GroupMessage%' order by id"
).fetchall()

data = []
for rid, name, content, ts in rows:
    try:
        d = json.loads(content)
    except Exception:
        continue
    segs = d.get("message") or []
    quote = None
    at = []
    text = ""
    for s in segs:
        t = s.get("type")
        if t == "plain":
            text += s.get("text", "")
        elif t == "at":
            at.append(f"@{s.get('name')}")
        elif t == "reply":
            quote = (s.get("sender_name"), (s.get("text") or "")[:60])
    data.append((rid, name, ts, text.strip(), quote, at))

for i, (rid, name, ts, text, quote, at) in enumerate(data):
    if not quote:
        continue
    nxt = None
    for j in range(i + 1, min(i + 4, len(data))):
        if data[j][1] == "bot":
            nxt = data[j]
            break
    print(f"[{rid}] {ts[:16]} {name} (at={' '.join(at) or '-'}) 引用[{quote[0]}]: {quote[1]!r}")
    print(f"      本条: {text[:80]!r}")
    if nxt:
        print(f"      → 机器人[{nxt[0]}]: {nxt[3][:110]!r}")
    else:
        print("      → 无回复")
