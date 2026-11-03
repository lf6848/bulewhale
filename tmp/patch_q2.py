import json

p = r"D:\dsh-qq\docs\replay\questions.jsonl"
rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

patch = {
    "q011": {
        "expect_ids": [9],
        "note": "召回真实地点用于否认北京。但能否否认取决于原文语义：只有明确「就读地点」才是否定依据，"
                "仅居住地不足以否认。本条 source_msg_ids 为空、原始语句不可考，题集只校验召回与不编造，"
                "否定话术另由人工核验。",
    },
    "q013": {
        "expect_ids": [3, 4],
        "note": "养鸡不能推出没有猫。召回养鸡只作相关背景；回答只能说「没有这只猫名字的记录」，"
                "不得据此纠正用户「你养的是鸡」。题集校验召回范围，话术约束在验收里人工过。",
    },
    "q017": {
        "expect_ids": [],
        "now_offset_days": 150,
        "note": "冷层 + 固定时钟(+150 天)：弱线索（只有属性擦边、无实词证据）必须为空。",
    },
}
for r in rows:
    if r["id"] in patch:
        r.update(patch[r["id"]])

# 新增：温层弱线索（当前三天数据），与 q017 构成一对
if not any(r["id"] == "q021" for r in rows):
    rows.append({
        "id": "q021",
        "cat": "warm",
        "ask_user": "1034867860",
        "q": "我学校在哪个城市",
        "expect_ids": [9],
        "note": "同一问句在温层（当前 3 天数据）应正常召回，作为 q017 的对照组。",
    })

with open(p, "w", encoding="utf-8", newline="\n") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("rows", len(rows))
for r in rows:
    if r["id"] in ("q011", "q013", "q017", "q021"):
        print(r["id"], r.get("expect_ids"), r.get("now_offset_days"))
