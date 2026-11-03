import sqlite3, json, statistics, time, os

DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.row_factory = sqlite3.Row
c = con.cursor()

print("== 基本 ==")
for r in c.execute("select count(*) n, min(created_at) a, max(created_at) b from memories"):
    print("memories=%s  first=%s  last=%s" % (r["n"], time.strftime("%m-%d %H:%M", time.localtime(r["a"] or 0)), time.strftime("%m-%d %H:%M", time.localtime(r["b"] or 0))))
print("integrity:", c.execute("pragma integrity_check").fetchone()[0])

print("\n== 按类型/来源 ==")
for r in c.execute("select type, source, count(*) n from memories group by type, source order by n desc"):
    print("  %-12s %-12s %d" % (r["type"], r["source"], r["n"]))

print("\n== 迁移后新增（10-29 17:00 之后）==")
cut = time.mktime(time.strptime("2026-10-29 17:00", "%Y-%m-%d %H:%M"))
c.execute("select count(*) from memories where created_at >= ?", (cut,))
print("  new_rows =", c.fetchone()[0])

print("\n== importance 分布 ==")
for r in c.execute("select round(importance,1) i, count(*) n from memories group by i order by i desc"):
    print("  %.1f  %d" % (r["i"], r["n"]))

print("\n== 强度/冷层（影子字段）==")
rows = list(c.execute("select strength_shadow, cold_shadow, recall_count, pinned, initial_strength_s from memories"))
st = [r["strength_shadow"] for r in rows if r["strength_shadow"]]
print("  (strength_shadow): n=%d min=%.1fs(%sh) median=%.1fh max=%.1fh" % (
    len(st), min(st), round(min(st)/3600, 2), statistics.median(st)/3600, max(st)/3600) if st else "  none")
print("  cold_shadow=1: %d / %d" % (sum(1 for r in rows if r["cold_shadow"]), len(rows)))
print("  pinned: %d" % sum(1 for r in rows if r["pinned"]))
print("  recall_count>0: %d  sum=%d" % (sum(1 for r in rows if r["recall_count"]), sum(r["recall_count"] or 0 for r in rows)))

print("\n== 影子日志 ==")
try:
    for r in c.execute("select count(*) n, min(ts) a, max(ts) b from shadow_log"):
        print("  rows=%d  %s → %s" % (r["n"],
              time.strftime("%m-%d %H:%M", time.localtime(r["a"])) if r["a"] else "-",
              time.strftime("%m-%d %H:%M", time.localtime(r["b"])) if r["b"] else "-"))
    print("  by mode:")
    for r in c.execute("select mode, count(*) n, sum(n_injected) inj, max(n_injected) mx, avg(n_candidates) cnd from shadow_log group by mode"):
        print("    %-10s n=%-3d inj=%-3d max_inj=%d avg_cand=%.1f" % (r["mode"], r["n"], r["inj"] or 0, r["mx"] or 0, r["cnd"] or 0))
    print("  top injected ids:")
    cnt = {}
    for r in c.execute("select injected_ids from shadow_log"):
        for x in (r["injected_ids"] or "").replace(" ", "").split(","):
            if x.isdigit():
                cnt[int(x)] = cnt.get(int(x), 0) + 1
    for mid, n in sorted(cnt.items(), key=lambda kv: -kv[1])[:10]:
        row = c.execute("select substr(content,1,40) as content, type, importance from memories where id=?", (mid,)).fetchone()
        print("    id=%-4d ×%-3d %s %s" % (mid, n, row["type"] if row else "?", (row["content"] if row else "?")))
    print("  notes 关键计数:")
    agg = {"bf_calls": 0, "bf_ids": 0, "bf_rejuve": 0, "zero": 0}
    for r in c.execute("select notes, n_injected from shadow_log"):
        nt = r["notes"] or ""
        if r["n_injected"] == 0:
            agg["zero"] += 1
        for k in ("bf_calls", "bf_ids", "bf_rejuve"):
            for part in nt.split():
                if part.startswith(k + "="):
                    try: agg[k] += int(part.split("=")[1])
                    except Exception: pass
    print("   ", agg)
except sqlite3.OperationalError as e:
    print("  shadow_log 不可用:", e)

print("\n== 其他表 ==")
for t in ("processed_messages", "reinforce_events", "memory_events", "memories_shadow"):
    try:
        print("  %-20s %d" % (t, c.execute("select count(*) from %s" % t).fetchone()[0]))
    except sqlite3.OperationalError as e:
        print("  %-20s err %s" % (t, e))
