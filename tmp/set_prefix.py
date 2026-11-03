import json
import shutil
import time

P = "/opt/astrbot/data/cmd_config.json"
shutil.copy(P, P + ".bak-prefix-" + time.strftime("%Y%m%d-%H%M%S"))
c = json.load(open(P, encoding="utf-8-sig"))
ps = c["provider_settings"]

ps["prompt_prefix"] = (
    "【工具使用】需要实时信息（新闻、价格、天气、赛事、最新版本、你不确定或可能过时的事）时，"
    "必须调用 web_search_anysearch 工具查询，参数只要 {\"query\": \"关键词\"}；"
    "需要正文再用 anysearch_extract 抓取网页。"
    "只能用上面工具列表里真实存在的工具名，不确定就先看列表，禁止臆造工具名。"
    "查完再用自己的话简短转述，并给出链接。"
)

json.dump(c, open(P, "w", encoding="utf-8-sig"), ensure_ascii=False, indent=2)
print("prompt_prefix set, len =", len(ps["prompt_prefix"]))
