import json
import sqlite3

db = "/AstrBot/data/data_v4.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

for label, pat in (("AT", '%"at"%'), ("REPLY", '%"Reply"%')):
    rows = c.execute(
        "select id, sender_name, user_id, content, created_at from platform_message_history "
        "where content like ? order by id desc limit 4",
        (pat,),
    ).fetchall()
    print(f"== {label} rows={len(rows)}")
    for r in rows:
        print(r[0], r[1], r[2], r[4])
        print("   ", r[3][:400])
