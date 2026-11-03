import datetime
import sqlite3

DB = "/opt/astrbot/data/data_v4.db"
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
db = sqlite3.connect(DB)
db.execute("UPDATE personas SET updated_at=? WHERE id=2", (now,))
db.commit()
row = db.execute("SELECT updated_at, length(system_prompt) FROM personas WHERE id=2").fetchone()
db.close()
print("updated_at=%r chars=%d" % (row[0], row[1]))
