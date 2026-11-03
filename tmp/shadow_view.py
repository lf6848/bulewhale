import sqlite3, re, time, statistics

DB = "/tmp/prod_snap.db"
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
con.row_factory = sqlite3.Row
c = con.cursor()

print("== memories_shadow ==")
cols = [r[1] for r in c.execute("pragma table_info(memories_shadow)")]
print("cols:", cols)
rows = list(c.execute("select * from memories_shadow"))
print("rows:", len(rows))
if rows:
    st = [r["strength"] for r in rows if "strength" in r.keys() and r["strength"]]
    if st:
        st_h = sorted(x / 86400.0 for x in st)
        print("strength(天): min=%.1f p25=%.1f median=%.1f p75=%.1f max=%.1f" % (
            st_h[0], st_h[len(st_h)//4], statistics.median(st_h), st_h[3*len(st_h)//4], st_h[-1]))
    for k in ("cold", "pinned", "recall_count"):
        if k in rows[0].keys():
            print(" %s: sum=%s nonzero=%d" % (k, sum(r[k] or 0 for r in rows), sum(1 for r in rows if r[k])))

print("\n== 真实提问 vs 注入 ==")
pat = re.compile(r"[?？]|吗|什么|哪|多少|怎么|为什么|是不是|有没有|记得")
tot = q = qinj = 0
for r in c.execute("select ts,text,mode,n_candidates,n_injected,injected_ids,tokens from shadow_log order by ts"):
    tot += 1
    isq = bool(pat.search(r["text"] or ""))
    if isq:
        q += 1
        if r["n_injected"]:
            qinj += 1
print(" rows=%d  像提问的=%d  其中注入>0 的=%d (%.0f%%)" % (tot, q, qinj, 100.0*qinj/max(q,1)))
print(" 全部注入>0 的行=%d (%.0f%%)" % (sum(1 for r in c.execute("select 1 from shadow_log where n_injected>0")),
                                      100.0*sum(1 for _ in c.execute("select 1 from shadow_log where n_injected>0"))/max(tot,1)))

print("\n== 最近 20 条实况 ==")
for r in list(c.execute("select ts,text,mode,n_candidates,n_injected,injected_ids,tokens,notes from shadow_log order by ts desc limit 20"))[::-1]:
    t = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
    txt = (r["text"] or "").replace("\n", " ")[:34]
    print("%s %-9s c=%d i=%d %-12s %s" % (t, r["mode"], r["n_candidates"], r["n_injected"], r["injected_ids"] or "-", txt))

print("\n== 零候选样本（看是否真无关）==")
for r in c.execute("select ts,text from shadow_log where n_candidates=0 order by ts desc limit 10"):
    print("  ", (r["text"] or "").replace("\n", " ")[:60])
