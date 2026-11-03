import sqlite3, re, time, statistics, json
from collections import Counter

DB = "/tmp/week_snap.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.row_factory = sqlite3.Row
c = con.cursor()

def ts(x):
    return time.strftime("%m-%d %H:%M", time.localtime(x)) if x else "-"

print("== 0. 库体 ==")
r = c.execute("select count(*) n, min(created_at) a, max(created_at) b from memories").fetchone()
print("memories=%d  %s → %s" % (r["n"], ts(r["a"]), ts(r["b"])))
print("integrity:", c.execute("pragma integrity_check").fetchone()[0])
print("类型:", dict(c.execute("select type, count(*) from memories group by type").fetchall()))
print("importance:", dict(c.execute("select round(importance,2), count(*) from memories group by 1 order by 1 desc").fetchall()))
print("非 summary 事实:", c.execute("select count(*) from memories where type!='summary'").fetchone()[0])

print("\n== 1. 灰度请求量 ==")
r = c.execute("select count(*) n, min(ts) a, max(ts) b, sum(n_injected) inj, sum(tokens) tok from shadow_log").fetchone()
span = (r["b"] - r["a"]) / 86400.0
print("请求=%d  跨度=%.2f 天  %s → %s" % (r["n"], span, ts(r["a"]), ts(r["b"])))
print("注入条次=%s  有注入的请求=%d (%.0f%%)  平均每请求注入=%.2f  注入 token 合计=%s" % (
    r["inj"], c.execute("select count(*) from shadow_log where n_injected>0").fetchone()[0],
    100.0*c.execute("select count(*) from shadow_log where n_injected>0").fetchone()[0]/r["n"],
    (r["inj"] or 0)/r["n"], r["tok"]))
print("按人:", dict(c.execute("select user_id, count(*) from shadow_log group by user_id order by 2 desc").fetchall()))
print("按模式:", dict(c.execute("select mode, count(*) from shadow_log group by mode").fetchall()))

print("\n== 2. 每条记忆被注入次数（霸榜检查）==")
cnt = Counter()
for row in c.execute("select injected_ids from shadow_log where n_injected>0"):
    for x in re.findall(r"\d+", row["injected_ids"] or ""):
        cnt[int(x)] += 1
total = sum(cnt.values())
print("被注入过的记忆数=%d / 总量=%d  总条次=%d" % (len(cnt), r["n"] and c.execute("select count(*) from memories").fetchone()[0], total))
top = cnt.most_common(12)
for mid, n in top:
    row = c.execute("select substr(content,1,34) t, type, importance, user_id from memories where id=?", (mid,)).fetchone()
    print("  id=%-4d ×%-3d %-12s I=%.2f %s" % (mid, n, row["type"] if row else "已删除", row["importance"] if row else 0,
                                                (row["t"] if row else "-")))
if total:
    top3 = sum(n for _, n in cnt.most_common(3))
    print("  top3 占比 = %.0f%%（越集中越像霸榜）" % (100.0*top3/total))

print("\n== 3. 证据命中 / 误注入 抽样 ==")
rows = list(c.execute("select ts,user_id,text,n_candidates,n_injected,injected_ids from shadow_log order by ts"))
print("零候选=%d  零注入=%d" % (sum(1 for x in rows if x["n_candidates"] == 0), sum(1 for x in rows if x["n_injected"] == 0)))
print("最近 12 条有注入的：")
for x in [y for y in rows if y["n_injected"]][-12:]:
    print("  %s u=%s i=%d %-14s %s" % (ts(x["ts"]), x["user_id"], x["n_injected"], x["injected_ids"],
                                       (x["text"] or "").replace("\n", " ")[:36]))

print("\n== 4. 兜底（旧写入器新增行缺字段）==")
bf_calls = bf_ids = bf_rej = 0
for row in c.execute("select notes from shadow_log"):
    for part in (row["notes"] or "").split():
        if part.startswith("bf_calls="): bf_calls += int(part.split("=")[1])
        elif part.startswith("bf_ids="): bf_ids += int(part.split("=")[1])
        elif part.startswith("bf_rejuve="): bf_rej += int(part.split("=")[1])
print("bf_calls 合计=%d  平均每请求=%.1f" % (bf_calls, bf_calls/max(len(rows),1)))
miss_ts = c.execute("select count(*) from memories where coalesce(last_reinforced_at,0)=0").fetchone()[0]
miss_s0 = c.execute("select count(*) from memories where coalesce(initial_strength_s,0)=0").fetchone()[0]
print("去重后缺 last_reinforced_at=%d  缺 initial_strength_s=%d  时间戳被抬高次数=%d" % (miss_ts, miss_s0, bf_rej))

print("\n== 5. 强度 / 冷层 ==")
st = [r["initial_strength_s"]/86400.0 for r in c.execute("select initial_strength_s from memories") if r["initial_strength_s"]]
if st:
    print("S0(天): min=%.1f median=%.1f max=%.1f" % (min(st), statistics.median(st), max(st)))
print("memories_shadow: rows=%d cold=%d recall_sum=%d" % (
    c.execute("select count(*) from memories_shadow").fetchone()[0],
    c.execute("select count(*) from memories_shadow where cold=1").fetchone()[0],
    c.execute("select coalesce(sum(recall_count),0) from memories_shadow").fetchone()[0]))

print("\n== 6. 越权复查 ==")
owner = {r[0]: r[1] for r in c.execute("select id, user_id from memories")}
bad = 0
for row in c.execute("select user_id, injected_ids from shadow_log where n_injected>0"):
    for x in re.findall(r"\d+", row["injected_ids"] or ""):
        if owner.get(int(x)) != row["user_id"]:
            bad += 1
print("越权注入条次=%d" % bad)
