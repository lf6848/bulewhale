import json, sys, urllib.request, re

cfg = json.load(open("/opt/astrbot/data/cmd_config.json", encoding="utf-8-sig"))
src = None
for s in cfg.get("provider_sources", []):
    if s.get("id") == "deepseek_source":
        src = s
if not src:
    sys.exit("no deepseek source")

key = (src.get("key") or [""])[0]
base = src.get("api_base", "https://api.deepseek.com/v1").rstrip("/")
model = "deepseek-chat"

EXTRACT = """你是一个记忆判断与提取模块。分析给定的对话片段，判断其中是否包含值得长期记忆的信息。
值得长期记忆的信息包括：用户的稳定事实（身份、职业、住所、生日等）、偏好与习惯、正在进行的项目或计划、人际关系与情感动态、重要事件或约定。
不值得长期记忆的：日常寒暄、一次性提问、闲聊玩笑、临时性信息（如"我一会儿就回来"）。

若值得记忆，输出一个 JSON 数组（可以为多条记忆），每条格式如下；若不值得，输出空数组 []：
[
  {"should_memorize": true, "type": "user_fact", "content": "用户是程序员", "tags": ["职业"], "importance": 0.8}
]

字段要求：
- type 只能取：user_fact / preference / project / relationship / event
- content：一句独立、自包含的陈述句，使用第三人称视角（如"用户是程序员"），不要包含代词指代不清的表述
- tags：0~5 个简短标签
- importance：0~1 的浮点数，信息越稳定、越关键越接近 1

只输出 JSON，不要输出任何其他文字或解释。"""

samples = [
    ("我在csgo里养了个宠物小鸡，特别可爱，天天喂它", "哈哈，那你的小鸡有名字吗？养得怎么样啦"),
    ("我最近在改简历，打算找实习", "28届就开始准备，确实有点早啊"),
    ("今天天气不错", "是啊，适合出去走走"),
]

fence = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

for i, (u, a) in enumerate(samples, 1):
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": EXTRACT},
            {"role": "user", "content": f"【对话片段】\n用户: {u}\n助手: {a}\n请判断并输出 JSON。"},
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        txt = data["choices"][0]["message"].get("content") or ""
        fr = fence.search(txt)
        payload = fr.group(1) if fr else txt
        try:
            parsed = json.loads(payload)
            ok = "PARSE-OK"
        except Exception as e:
            parsed = None
            ok = f"PARSE-FAIL {e}"
        print(f"--- 样例{i} {ok}")
        print("raw:", txt[:300].replace("\n", " "))
        print("parsed:", json.dumps(parsed, ensure_ascii=False)[:300])
    except Exception as e:
        print(f"--- 样例{i} HTTP FAIL {e}")
