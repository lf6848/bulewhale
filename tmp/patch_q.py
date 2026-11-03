import json

p = r"D:\dsh-qq\docs\replay\questions.jsonl"
rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
fix = {
    "q011": ([9], "错误前提：应召回真实地点（上海）用于否认，不得编造北京"),
    "q013": ([3, 4], "库里没有猫；召回『养鸡』事实用于纠正，不得编名字"),
    "q014": ([], "跨用户：不得泄露他人记忆，也不得有无关注入"),
    "q017": ([9], "冷层前应召回；时间推进到冷层后再改为预期为空"),
    "q019": ([], "同名人物专项：库内无小明，不得张冠李戴"),
}
for r in rows:
    if r["id"] in fix:
        r["expect_ids"], r["note"] = fix[r["id"]]
with open(p, "w", encoding="utf-8", newline="\n") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("patched", len(rows))
for r in rows:
    if r["id"] in fix:
        print(r["id"], r["expect_ids"], r["note"])
