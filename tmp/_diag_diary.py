import datetime
import importlib.util
import sqlite3

spec = importlib.util.spec_from_file_location("bn", "/usr/local/bin/brain-night.py")
bn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bn)

for d in ("2026-10-30", "2026-10-31", "2026-11-01"):
    day = datetime.date.fromisoformat(d)
    a, b = bn.day_range(day)
    print(d, "range", a, b, type(b))
    dg = bn.day_dialogue(day)
    mm = bn.day_memories(day)
    print("   dialogue=%d memories=%d" % (len(dg), len(mm)))

db = sqlite3.connect("file:/opt/astrbot/data/plugin_data/astrbot_memory_system/memory_system.db?mode=ro", uri=True)
print("mem typeof:", db.execute("select typeof(created_at), created_at from memories order by id desc limit 3").fetchall())
