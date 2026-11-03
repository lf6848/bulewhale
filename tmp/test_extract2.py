import json, re, sys, urllib.request

sys.path.insert(0, "/opt/astrbot/data/plugins/astrbot_plugin_memory_system")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "prompts", "/opt/astrbot/data/plugins/astrbot_plugin_memory_system/core/prompts.py")
prompts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prompts)
EXTRACT = prompts.EXTRACT_SYSTEM_PROMPT

cfg = json.load(open("/opt/astrbot/data/cmd_config.json", encoding="utf-8-sig"))
src = next(s for s in cfg["provider_sources"] if s["id"] == "deepseek_source")
key = (src.get("key") or [""])[0]
base = src.get("api_base", "https://api.deepseek.com/v1").rstrip("/")

samples = [
    ("我在csgo里养了个宠物小鸡，特别可爱，天天喂它", "哈哈，那你的小鸡有名字吗？"),
    ("我最近在改简历，打算找实习", "28届就开始准备，确实有点早啊"),
    ("今天天气不错", "是啊，适合出去走走"),
    ("在吗", "在的，怎么啦"),
    ("我不吃香菜，闻到就想吐", "记住了，以后点菜避开香菜"),
]

fence = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
thr = json.load(open("/opt/astrbot/data/config/astrbot_plugin_memory_system_config.json",
                     encoding="utf-8-sig"))["importance_threshold"]

for i, (u, a) in enumerate(samples, 1):
    body = {"model": "deepseek-chat", "temperature": 0.3, "messages": [
        {"role": "system", "content": EXTRACT},
        {"role": "user", "content": f"【对话片段】\n用户: {u}\n助手: {a}\n请判断并输出 JSON。"},
    ]}
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        txt = json.loads(r.read())["choices"][0]["message"].get("content") or ""
    m = fence.search(txt)
    try:
        parsed = json.loads(m.group(1) if m else txt)
    except Exception as e:
        parsed = f"PARSE-FAIL {e}"
    kept = [p for p in parsed if isinstance(p, dict) and p.get("importance", 0) >= thr] if isinstance(parsed, list) else []
    print(f"--- 样例{i} 用户:{u[:18]}")
    print("  输出:", json.dumps(parsed, ensure_ascii=False)[:220])
    print(f"  过阈值({thr}) 保留 {len(kept)} 条")
