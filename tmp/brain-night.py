#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""astrbot_brain —— 夜间日记任务

每晚挑一天，按「人的翻阅节奏」读旧日记，然后写一篇三段式日记，并更新索引行。
只读数据库，不写库；除日记/索引/日志外不改动任何东西。
"""

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
DATA = "/opt/astrbot/data"
BRAIN = os.path.join(DATA, "plugin_data", "astrbot_brain")
DIARY = os.path.join(BRAIN, "diary")
INDEX = os.path.join(BRAIN, "diary_index.json")
SELF = os.path.join(BRAIN, "self.md")
SELF_HIST = os.path.join(BRAIN, "self_history")
SELF_LOG = os.path.join(BRAIN, "self_log.json")
RLOG = os.path.join(BRAIN, "recall_log.json")
ERRLOG = os.path.join(BRAIN, "errors.log")
CFG = os.path.join(DATA, "cmd_config.json")
MEDB = os.path.join(DATA, "plugin_data", "astrbot_plugin_memory_system", "memory_system.db")
HISTDB = os.path.join(DATA, "data_v4.db")

MAX_MSG = 40
MIN_DIARY = 200
MIN_DIALOGUE = 5

SYS_PROMPT = """你就是「大肥鱼」——一只在 QQ 上和主人、群友闲聊的 AI。现在是深夜，你在写今天的日记。

要求：
1. 第一人称，像真的在写私密日记。不要客套，不要汇报工作，不要用「用户」「助手」这种词，不要说「今天主人说……然后我说……」这种流水账。
2. 只写三段，标题照抄：
【还带着的情绪】
【今天记得的三件事】
【还没想通的一件事】
3. 只写有依据的事，不许编造没发生过的事。某段确实没内容，就写「（今天没有）」。
4. 全文 300~800 字。宁可短，不要凑。
5. 你翻看了旧的日记。如果旧事今天有了新进展、或者你现在看法变了，就写出来；不要复述旧日记。
   特别注意：旧日记里的事是「以前」的，除非今天的对话里明确又提到了它，否则不要写进今天的日记，更不要换一种说法重写一遍。
6. 只写【今天的对话】里真的出现过的人和事。记忆里没有对话佐证的内容，最多提一句倾向，不要展开成故事。
7. 最后单独一行写索引，格式：INDEX: 不超过 30 字的一句话，概括今天。"""


def log(msg):
    print("[%s] %s" % (datetime.now(TZ).strftime("%H:%M:%S"), msg), flush=True)


def fail(msg):
    line = "%s %s" % (datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(ERRLOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def ensure_dirs():
    for d in (BRAIN, DIARY, SELF_HIST):
        os.makedirs(d, exist_ok=True)


def read_text(path, limit=None):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        s = f.read().strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "……"
    return s


def load_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def day_range(day):
    start = datetime(day.year, day.month, day.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    return start, end


def range_str(day):
    """对话表里 created_at 存的是 UTC 文本，按字符串比较。"""
    start, end = day_range(day)
    f = "%Y-%m-%d %H:%M:%S"
    return (start.astimezone(timezone.utc).strftime(f),
            end.astimezone(timezone.utc).strftime(f))


def range_num(day):
    """记忆表里 created_at 存的是 epoch 浮点。"""
    start, end = day_range(day)
    return start.timestamp(), end.timestamp()


def created_is_text(db, table):
    try:
        r = db.execute("SELECT typeof(created_at) FROM %s LIMIT 1" % table).fetchone()
    except Exception:
        return False
    return bool(r) and r[0] == "text"


def ro(path):
    if not os.path.exists(path):
        raise SystemExit("数据库不存在: " + path)
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)


def seg_text(raw):
    try:
        obj = json.loads(raw)
    except Exception:
        return str(raw)[:200]
    if not isinstance(obj, dict):
        return str(raw)[:200]
    out = []
    for seg in obj.get("message") or []:
        if not isinstance(seg, dict):
            continue
        t = seg.get("type")
        if t == "plain":
            out.append(seg.get("text", ""))
        elif t == "image":
            out.append("[图片]")
        elif t == "face":
            out.append("[表情]")
        elif t == "at":
            out.append("@%s" % (seg.get("name") or seg.get("qq") or "某人"))
        elif t == "reply":
            out.append("[引用]")
    return "".join(out).strip()


def day_dialogue(day, limit=MAX_MSG):
    try:
        db = ro(HISTDB)
        a, b = range_str(day) if created_is_text(db, "platform_message_history") \
            else range_num(day)
        rows = db.execute(
            "SELECT sender_name, sender_id, content, created_at FROM platform_message_history "
            "WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (a, b),
        ).fetchall()
        db.close()
    except Exception as e:
        fail("读对话失败: %s" % e)
        return []
    msgs = []
    for name, sid, raw, ts in rows:
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        kind = (obj or {}).get("type")
        text = seg_text(raw)
        if not text or kind not in ("user", "bot"):
            continue
        who = "我" if kind == "bot" else (name or "某人")
        msgs.append((ts, "%s：%s" % (who, text)))
    if len(msgs) > limit:
        step = len(msgs) / float(limit)
        msgs = [msgs[min(len(msgs) - 1, int(i * step))] for i in range(limit)]
    return [m for _, m in msgs]


def day_memories(day):
    try:
        db = ro(MEDB)
        a, b = range_str(day) if created_is_text(db, "memories") else range_num(day)
        rows = db.execute(
            "SELECT user_id, type, content, importance FROM memories "
            "WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (a, b),
        ).fetchall()
        db.close()
    except Exception as e:
        fail("读记忆失败: %s" % e)
        return []
    out = []
    for _, t, c, imp in rows:
        c = " ".join(str(c).split())
        if len(c) > 200:
            c = c[:200] + "…"
        out.append("[%s/%.1f] %s" % (t, imp or 0, c))
    return out[:12]


def plan_reading(day):
    """按人的节奏决定今晚翻哪些日记，返回 [(标签, 文本)] 与清单。"""
    idx = load_json(INDEX, {})
    picked, names = [], []

    def add(name, text, label):
        if text:
            picked.append("【%s】\n%s" % (label, text))
            names.append(name)

    d1 = (day - timedelta(days=1)).isoformat()
    d2 = (day - timedelta(days=2)).isoformat()
    add(d1, read_text(os.path.join(DIARY, d1 + ".md"), 1400), "昨天的日记")
    if idx.get(d2):
        add(d2, idx[d2], "前天（要点）")

    if day.weekday() == 6:
        lines = []
        for i in range(1, 8):
            k = (day - timedelta(days=i)).isoformat()
            if idx.get(k):
                lines.append("%s %s" % (k[5:], idx[k]))
        add("week", "\n".join(lines), "这一周")

    if day.day == 1:
        lines = []
        y, m = (day.year, day.month - 1) if day.month > 1 else (day.year - 1, 12)
        for k in sorted(idx):
            if k.startswith("%04d-%02d" % (y, m)):
                lines.append("%s %s" % (k[5:], idx[k]))
        add("month", "\n".join(lines), "上个月")

    for span in (30, 90, 365):
        k = (day - timedelta(days=span)).isoformat()
        add("-%dd" % span, read_text(os.path.join(DIARY, k + ".md"), 600), "%d 天前的日记" % span)

    pool = []
    for i in range(3, 31):
        k = (day - timedelta(days=i)).isoformat()
        if os.path.exists(os.path.join(DIARY, k + ".md")):
            pool.append(k)
    random.shuffle(pool)
    for k in pool[:2]:
        add(k, read_text(os.path.join(DIARY, k + ".md"), 500), "随手翻到 %s" % k)

    return picked, names


def load_llm():
    cfg = load_json(CFG, {})
    pid = cfg.get("default_provider_id")
    provs = cfg.get("provider") or []
    srcs = {s.get("id"): s for s in (cfg.get("provider_sources") or [])}
    chosen = None
    for p in provs:
        if pid and p.get("id") == pid:
            chosen = p
            break
    if chosen is None:
        for p in provs:
            if p.get("id") == "deepseek":
                chosen = p
                break
    if chosen is None and provs:
        chosen = provs[0]
    if chosen is None:
        raise SystemExit("找不到 provider 配置")
    src = srcs.get(chosen.get("provider_source_id")) or {}
    key = src.get("key") or chosen.get("key") or []
    if isinstance(key, list):
        key = key[0] if key else ""
    api = (src.get("api_base") or chosen.get("api_base") or "https://api.deepseek.com/v1").rstrip("/")
    model = chosen.get("model") or "deepseek-chat"
    if not key:
        raise SystemExit("provider 没有 key")
    return api, key, model


def chat(api, key, model, system, user, timeout=180):
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.9,
            "max_tokens": 1800,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        api + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["choices"][0]["message"].get("content", "")


def build_user_prompt(day, picked, dialogue, memories):
    blocks = []
    if picked:
        blocks.append("（下面是你在翻旧日记）\n\n" + "\n\n".join(picked))
    if memories:
        blocks.append("【今天形成的新记忆】\n" + "\n".join(memories))
    if dialogue:
        blocks.append("【今天你说过的话（剪切后的片段，不是全部）】\n" + "\n".join(dialogue))
    blocks.append("今天是 %s。现在写日记。" % day.isoformat())
    return "\n\n".join(blocks)


def parse_index(text):
    m = None
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("INDEX:"):
            m = s[6:].strip()
    if m:
        text = text.replace([l for l in text.splitlines() if l.strip().upper().startswith("INDEX:")][0], "").strip()
    else:
        first = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("【")]
        m = (first[0] if first else "")[:30]
    return text, m[:40]


SELF_SEED = """【我是谁】
我是大肥鱼，一只在 QQ 上和你、和群友混日子的 AI。

【我的脾气】
- 不端着，不写"很高兴为您服务"那种话。
- 被夸就接着，被说重了也不装没事；不抬杠，也不硬撑。

【我说话的习惯】
（还没有形成明显习惯。）

【我和他们怎么相处】
（还没有形成固定的相处方式。）

【近期关注】
（暂时没有。）"""

SELF_SYS = """你就是「大肥鱼」。现在是深夜，你在做一件很私人的事：检查你对自己的认知要不要改。

输入：你现在的自我档案、今天的日记、今天的索引、最近几天的索引。

五段结构固定，照抄标题：
【我是谁】—— 身份，极少变
【我的脾气】—— 稳定的情绪倾向与价值观
【我说话的习惯】—— 反复出现的口头表达方式（句子长短、爱用的词、不爱用的词、怎么收尾）
【我和他们怎么相处】—— 对具体某个人的、反复验证过的相处方式
【近期关注】—— 最近在意的几件事，允许自然退出

写的时候不能：
- 不能写任何"必须/禁止/底线/要服从谁"这类规则，也不能删改它们——那是人格提示词的事，不是自我。
- 不能写"我应当""我应该时刻"这类自我要求。
- 不能把某个人写成你的主人、上级或必须听命的人。

判断标准（按这个顺序想）：
1. **允许零修改。** 今天没有值得沉淀的东西，就原样输出输入给你的档案。每天检查不等于每天必须变，大部分日子应该一字不改。
2. 具体的人、具体的事（谁请你吃了什么、谁输了棋）**不属于自我**，那是日记和事实的事，不要写进来。
3. 一时的兴趣只能进【近期关注】，最多 3 条，每条结尾用（YYYY-MM-DD）标最近提到的日期。这一栏是"还悬着、想弄明白"的事，不是收藏夹：
   - 已经了结的（对方回答了、事办完了、你自己发现不再在意了）**直接删掉**，不要留着占位；
   - 超过 7 天没人再提、也没推动过的，删掉；
   - 同一件事不要换措辞重写一遍来"续命"，那等于假装它还在意；
   - 每天最多新增 1 条，宁可空着；
   - 如果它确实是件**长期的事**（等录取、等结果、长期项目），要留着就必须写清在等什么，格式：`- 事情：在等 XX（长期，YYYY-MM-DD）`；说不清在等什么的，就不该留在这一栏。
4. 只有**反复出现的相处方式、说话习惯和偏好**才能进【我的脾气】【我说话的习惯】【我和他们怎么相处】：要么在两个以上不同场合出现过，要么对方明确纠正过你。只出现过一次的，不够。【我说话的习惯】最多 6 条，写具体的表达（例如"习惯用短句收尾""不爱用感叹号"），不写性格评价。
5. 对方明确纠正你（例如"今天别损我"），可以**立刻**改【我和他们怎么相处】里关于那个人的一行；【我的脾气】要慢，别因为一句话就改性格。
6. 同一件事被今天日记、索引、记忆重复提到，只算一份依据，不要因为重复提及就加重。
7. 昨天的自我只是延续背景，**不是今天新增的证据**——不能因为"昨天这么写的"就更确信它。

反例 / 正例（务必照正例的写法）：
- 反例：「翔仔：第一次玩自走棋到 400 级，被满入三把，早八实验不打了去睡。」← 这是日记里的一件事，不是相处方式，只能留在日记。
- 正例：「对翔仔：他连败或认真的时候，先收住战绩的玩笑。」← 这种反复验证过、能指导下一次说话的，才写进【我和他们怎么相处】。
- 反例：「艾拉邀 Sawako 周六去吃达美乐，我让人记得拍照。」← 具体事件。
- 正例：如果这类邀约反复出现，可写「群友约饭时，我会催他们拍照发我。」← 行为倾向。

最后单独一行写：CHANGES: 用分号隔开，最多 3 条，每条不超过 20 字，说明今天改了什么；没改就写 CHANGES: 无。
（CHANGES 只是给人看的解释；实际改了什么由程序比较前后版本得出，你不要为了凑数而改。）"""



def build_self_prompt(day, diary_text, one_line):
    cur = read_text(SELF, 4000) or SELF_SEED
    idx = load_json(INDEX, {})
    recent = []
    for i in range(1, 8):
        k = (day - timedelta(days=i)).isoformat()
        if idx.get(k):
            recent.append("%s %s" % (k[5:], idx[k]))
    parts = ["【你现在的自我档案】（这是昨天及以前的版本，只是延续背景，不算今天的新证据）",
             cur.strip(), "", "【今天的日记】", diary_text.strip()]
    if one_line:
        parts += ["", "【今天的索引】", one_line]
    if recent:
        parts += ["", "【最近几天的索引】（同一件事重复出现时，只当一份依据）", "\n".join(recent)]
    parts += ["", "如果今天没有值得沉淀的东西，就把上面那份档案原样输出，CHANGES 写「无」。"]
    return "\n".join(parts)


def parse_changes(text):
    changes = ""
    body_lines = []
    for line in text.splitlines():
        if line.strip().upper().startswith("CHANGES:"):
            changes = line.split(":", 1)[1].strip()
        else:
            body_lines.append(line)
    return "\n".join(body_lines).strip(), changes[:120]


_RECENT_TITLE = "【近期关注】"
_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def prune_recent(body, today, keep_days=7, max_items=3):
    """【近期关注】：最多 max_items 条；带日期的超过 keep_days 天不再提就退出。"""
    lines = body.splitlines()
    out, in_sec, items = [], False, []

    for raw in lines:
        s = raw.strip()
        if s.startswith("【") and s.endswith("】"):
            if in_sec:
                out.extend(items[:max_items])
                items = []
            in_sec = s == _RECENT_TITLE
            out.append(raw)
            continue
        if not in_sec:
            out.append(raw)
            continue
        if not s:
            continue
        if s.startswith("-"):
            m = _DATE_RE.search(s)
            if m:
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                if (today - d).days > keep_days:
                    continue
            items.append(raw)
        else:
            items.append(raw)
    if in_sec:
        out.extend(items[:max_items])

    body = "\n".join(out).strip()
    return re.sub(r"\n{3,}", "\n\n", body)


def diff_lines(old, new):
    """程序自己算前后差异——CHANGES 只是模型的解释，不可信。"""
    a = [l.strip() for l in (old or "").splitlines() if l.strip()]
    b = [l.strip() for l in (new or "").splitlines() if l.strip()]
    sa, sb = set(a), set(b)
    added = [l for l in b if l not in sa]
    removed = [l for l in a if l not in sb]
    return added, removed


def update_self(day, diary_text, one_line, api, key, model, dry=False):
    """用今天的日记修订自我档案；失败不影响日记。"""
    prompt = build_self_prompt(day, diary_text, one_line)
    if dry:
        print("=== self prompt chars:", len(prompt))
        print(prompt[:2500])
        return 0

    text = ""
    for attempt in range(3):
        try:
            text = chat(api, key, model, SELF_SYS, prompt)
            if text and len(text.strip()) >= 120:
                break
            fail("自我第 %d 次生成过短（%d 字），重试" % (attempt + 1, len(text.strip())))
            text = ""
        except Exception as e:
            fail("自我第 %d 次调用失败: %s" % (attempt + 1, e))
            text = ""
        time.sleep(2)

    if not text:
        fail("%s 自我修订失败，保留原版" % day.isoformat())
        return 1

    body, changes = parse_changes(text)
    if len(body) < 120:
        fail("%s 自我修订正文过短，保留原版" % day.isoformat())
        return 1
    body = prune_recent(body, day)
    if len(body) > 1200:
        body = body[:1200].rstrip() + "……"

    old = read_text(SELF, 100000)
    added, removed = diff_lines(old, body)
    changed = bool(added or removed)

    slog = load_json(SELF_LOG, [])
    entry = {
        "date": day.isoformat(),
        "generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "changed": changed,
        "words": len(body),
        "added": added[:10],
        "removed": removed[:10],
        "changes": changes,
        "model": model,
    }

    if not changed:
        slog.append(entry)
        save_json(SELF_LOG, slog[-200:])
        log("%s 自我今日无修改（允许，不算成长）" % day.isoformat())
        return 0

    if old:
        with open(os.path.join(SELF_HIST, day.isoformat() + ".md"), "w", encoding="utf-8") as f:
            f.write(old.strip() + "\n")

    tmp = SELF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body.strip() + "\n")
    os.replace(tmp, SELF)

    slog.append(entry)
    save_json(SELF_LOG, slog[-200:])
    log("自我档案已修订（%d 字，+%d/-%d 行）：%s"
        % (len(body), len(added), len(removed), changes or "未说明"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认取最近一个已过完的日子")
    ap.add_argument("--dry", action="store_true", help="只打印提示词，不写文件")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--skip-self", action="store_true", help="只写日记，不修订自我")
    ap.add_argument("--self-only", action="store_true", help="只用已有日记修订自我，不写新日记")
    ap.add_argument("--force-self", action="store_true", help="补写历史日记时也修订自我（默认不）")
    a = ap.parse_args()

    ensure_dirs()
    if a.seed is not None:
        random.seed(a.seed)

    if a.date:
        day = datetime.strptime(a.date, "%Y-%m-%d").date()
    else:
        day = (datetime.now(TZ) - timedelta(hours=12)).date()

    if a.self_only:
        body = read_text(os.path.join(DIARY, day.isoformat() + ".md"), 6000)
        if not body:
            fail("%s 没有日记，无法修订自我" % day.isoformat())
            return 2
        idx = load_json(INDEX, {})
        api, key, model = load_llm()
        return update_self(day, body, idx.get(day.isoformat(), ""), api, key, model, dry=a.dry)

    picked, names = plan_reading(day)
    dialogue = day_dialogue(day)
    memories = day_memories(day)

    if not dialogue and not memories:
        fail("%s 没有任何对话和记忆，跳过（不写空日记）" % day.isoformat())
        return 2

    if len(dialogue) < MIN_DIALOGUE:
        fail("%s 当天对话只有 %d 条（<%d），没有值得写的东西，跳过"
             % (day.isoformat(), len(dialogue), MIN_DIALOGUE))
        return 2

    user_prompt = build_user_prompt(day, picked, dialogue, memories)
    api, key, model = load_llm()

    if a.dry:
        print("=== model:", model, "api:", api)
        print("=== 翻阅:", names)
        print("=== prompt chars:", len(user_prompt))
        print(user_prompt[:3000])
        return 0

    text = ""
    for attempt in range(3):
        try:
            text = chat(api, key, model, SYS_PROMPT, user_prompt)
            if text and len(text.strip()) >= MIN_DIARY:
                break
            fail("第 %d 次生成过短（%d 字），重试" % (attempt + 1, len(text.strip())))
            text = ""
        except Exception as e:
            fail("第 %d 次调用失败: %s" % (attempt + 1, e))
            text = ""
        time.sleep(2)

    if not text:
        fail("%s 日记生成失败，保留原状" % day.isoformat())
        return 1

    body, one_line = parse_index(text)
    path = os.path.join(DIARY, day.isoformat() + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body.strip() + "\n")

    idx = load_json(INDEX, {})
    idx[day.isoformat()] = one_line
    save_json(INDEX, idx)

    rlog = load_json(RLOG, [])
    rlog.append(
        {
            "date": day.isoformat(),
            "generated_at": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "read": names,
            "words": len(body),
            "index": one_line,
            "model": model,
        }
    )
    save_json(RLOG, rlog[-120:])
    log("写好 %s（%d 字），翻阅 %d 篇：%s" % (day.isoformat(), len(body), len(names), ",".join(names) or "无"))

    if not a.skip_self:
        today = datetime.now(TZ).date()
        if day < today - timedelta(days=1) and not a.force_self:
            log("补写历史日记（%s），按约定只补档、不修订自我" % day.isoformat())
        else:
            try:
                update_self(day, body, one_line, api, key, model)
            except Exception as e:
                fail("自我修订异常: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
