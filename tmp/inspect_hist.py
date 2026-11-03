import json, sqlite3

c = sqlite3.connect("/opt/astrbot/data/data_v4.db")
c.row_factory = sqlite3.Row
rows = c.execute(
    "select id,sender_id,sender_name,content,created_at from platform_message_history "
    "order by id desc limit 6"
).fetchall()
for r in rows:
    try:
        obj = json.loads(r["content"])
    except Exception:
        obj = {}
    typ = obj.get("type")
    texts = []
    for seg in obj.get("message") or []:
        if isinstance(seg, dict):
            texts.append(seg.get("text") or seg.get("type"))
    print(r["id"], r["created_at"], "sender=", r["sender_id"], "name=", r["sender_name"],
          "type=", typ, "text=", ("".join(str(t) for t in texts))[:60])

print("=== 时间范围 ===")
print(c.execute("select min(created_at), max(created_at), count(*) from platform_message_history").fetchone())
print("=== 各类型计数 ===")
for r in c.execute("select json_extract(content,'$.type') t, count(*) from platform_message_history group by t"):
    print(dict(r))
