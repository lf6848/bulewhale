# -*- coding: utf-8 -*-
"""备份并替换 personas 表 id=2 的 system_prompt。"""
import json
import os
import sqlite3
import time

DB = "/opt/astrbot/data/data_v4.db"
NEW = "/tmp/persona_v2.md"
BAK = "/opt/astrbot/data/backups"

os.makedirs(BAK, exist_ok=True)
text = open(NEW, encoding="utf-8").read().strip()

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
row = db.execute("SELECT * FROM personas WHERE id=2").fetchone()
if row is None:
    raise SystemExit("persona id=2 not found")

ts = time.strftime("%Y%m%d-%H%M%S")
path = os.path.join(BAK, "persona-id2-%s.json" % ts)
with open(path, "w", encoding="utf-8") as f:
    json.dump(dict(row), f, ensure_ascii=False, indent=1)

old_len = len(row["system_prompt"] or "")
db.execute("UPDATE personas SET system_prompt=?, updated_at=? WHERE id=2",
           (text, int(time.time())))
db.commit()

chk = db.execute("SELECT length(system_prompt) FROM personas WHERE id=2").fetchone()[0]
db.close()
print("backup:", path)
print("old_chars=%d new_chars=%d" % (old_len, chk))
print("head:", text.splitlines()[0])
