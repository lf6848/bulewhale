import json

P = "/opt/astrbot/data/config/astrbot_proactive_v2_config.json"
with open(P, encoding="utf-8") as f:
    cfg = json.load(f)

cfg.pop("interval_minutes", None)
cfg.pop("focus_cooldown_days", None)
cfg["interval_mean_minutes"] = 90
cfg["interval_min_minutes"] = 30
cfg["interval_max_minutes"] = 120
cfg["focus_enabled"] = True
cfg["focus_per_day"] = 1
cfg["focus_retry_minutes"] = 90
cfg["focus_wait_hours"] = 24
cfg["group_idle_minutes"] = 30
cfg["targets"] = [
    {"umo": "aiocqhttp:FriendMessage:1034867860", "label": "私聊", "kind": "private",
     "weight": 3, "max_per_day": 6},
    {"umo": "aiocqhttp:GroupMessage:726921160", "label": "群聊", "kind": "group",
     "weight": 2, "max_per_day": 3, "types": ["interest", "care", "own"]},
]

order = [
    "enabled", "umo", "targets",
    "interval_mean_minutes", "interval_min_minutes", "interval_max_minutes",
    "active_hour_start", "active_hour_end", "max_per_day",
    "deferred_cooldown_hours", "web_enabled", "web_results", "max_chars",
    "recent_dialogue", "min_gap_after_proactive_minutes",
    "focus_enabled", "focus_per_day", "focus_retry_minutes", "focus_wait_hours", "group_idle_minutes",
    "own_share_enabled", "own_share_per_day", "own_share_ratio",
    "browse_queries", "browse_sources", "titles_per_source",
    "deep_dive", "dive_results", "dive_chars",
    "think_step", "veto_step", "veto_own_only", "veto_retry", "interest_max",
]
out = {k: cfg[k] for k in order if k in cfg}
for k, v in cfg.items():
    if k not in out:
        out[k] = v

with open(P, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out.get("targets"), ensure_ascii=False))
