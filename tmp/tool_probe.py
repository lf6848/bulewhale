import json
import urllib.request

cfg = json.load(open("/AstrBot/data/cmd_config.json", encoding="utf-8-sig"))
src = {s["id"]: s for s in cfg["provider_sources"]}["deepseek_source"]
key = src["key"][0] if isinstance(src["key"], list) else src["key"]
base = src["api_base"].rstrip("/")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "anysearch_search",
        "description": "联网搜索实时信息，返回网页标题、链接与摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "number", "description": "返回条数，默认 5"},
            },
            "required": ["query"],
        },
    },
}]

MSGS = [
    {"role": "system", "content": "你是 QQ 群里的助手，可以用 anysearch_search 查实时信息。"},
    {"role": "user", "content": "帮我搜一下今天有什么值得看的科技新闻"},
]

payload = {
    "model": "deepseek-chat",
    "messages": MSGS,
    "tools": TOOLS,
    "tool_choice": "auto",
    "temperature": 0.3,
}
req = urllib.request.Request(
    base + "/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=90) as r:
    data = json.load(r)

msg = data["choices"][0]["message"]
print("finish_reason:", data["choices"][0].get("finish_reason"))
print("tool_calls:", json.dumps(msg.get("tool_calls"), ensure_ascii=False)[:400])
print("content:", (msg.get("content") or "")[:200])
