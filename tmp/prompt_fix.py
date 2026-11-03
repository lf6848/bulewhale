import json, shutil, time

base = "/opt/astrbot/data/plugins/astrbot_plugin_memory_system"
stamp = time.strftime("%Y%m%d-%H%M%S")

NEW = '''EXTRACT_SYSTEM_PROMPT = """你是一个记忆判断与提取模块。分析给定的对话片段，判断其中是否包含值得长期记忆的信息。

【重要判断原则】
问自己：这句话如果在一周后、在另一个聊天窗口里提起，是否仍然成立、仍然有用？
- 成立 → 值得记（即使用户是用玩笑、吐槽、随口一提的语气说出来的）
- 不成立（只是当下的寒暄、情绪、临时状态）→ 不记

【值得长期记忆】
1. 稳定事实：身份、职业、学校、年级、年龄、居住地、家庭情况
2. 偏好与习惯：喜欢/讨厌什么、作息、常做的事、回避的事
3. 拥有物与长期投入：宠物、游戏账号与游戏内养成/资产（例如"在 CSGO 里养了宠物小鸡"）、收藏、设备、作品
4. 进行中的项目与计划：求职、学习、创作、创业、旅行安排
5. 人际关系与情感动态：和谁关系好、在意谁、发生过什么约定
6. 重要经历与事件：发生过的、影响情绪或生活的事

【不值得记忆】
- 纯粹的寒暄、道别、应答（"在吗""好的""哈哈"）
- 一次性提问或信息查询
- 严格意义上的临时状态（"我一会儿出门"）
- 完全没有信息量的玩笑

【关键】不要因为语气轻松就判定为"闲聊玩笑"而丢弃。用户随口说的"我在 csgo 里养了只宠物小鸡"，是一条具体的、持久的个人事实，必须记录。

若值得记忆，输出一个 JSON 数组（可以为多条记忆），每条格式如下；若不值得，输出空数组 []：
[
  {
    "should_memorize": true,
    "type": "user_fact",
    "content": "用户在 CSGO 中养了一只宠物小鸡",
    "tags": ["游戏", "CSGO", "宠物"],
    "importance": 0.6
  }
]

字段要求：
- type 只能取：user_fact / preference / project / relationship / event
- content：一句独立、自包含的陈述句，使用第三人称视角（如"用户是程序员"），不要包含代词指代不清的表述
- tags：0~5 个简短标签
- importance：0~1 的浮点数。稳定客观信息 0.6~0.9，一般爱好与拥有物 0.5~0.7，短暂但可复用的 0.3~0.5

只输出 JSON，不要输出任何其他文字或解释。"""'''

p = f"{base}/core/prompts.py"
shutil.copy(p, f"{p}.bak-prompt-{stamp}")
s = open(p, encoding="utf-8").read()

start = s.index('EXTRACT_SYSTEM_PROMPT = """')
end = s.index('"""', s.index('只输出 JSON', start)) + 3
old = s[start:end]
s = s[:start] + NEW + s[end:]
open(p, "w", encoding="utf-8").write(s)
print("旧提示词长度", len(old), "→ 新", len(NEW))

# 阈值 0.5 → 0.35
cp = "/opt/astrbot/data/config/astrbot_plugin_memory_system_config.json"
shutil.copy(cp, f"{cp}.bak-{stamp}")
cfg = json.load(open(cp, encoding="utf-8-sig"))
cfg["importance_threshold"] = 0.35
json.dump(cfg, open(cp, "w", encoding="utf-8"), ensure_ascii=False, indent=4)
print("importance_threshold:", cfg["importance_threshold"])
