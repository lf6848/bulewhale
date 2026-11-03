# -*- coding: utf-8 -*-
"""离线跑回放题集：用影子引擎（只读库、不写影子表）逐题计算并对比预期。"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import ShadowEngine  # noqa: E402

DB = "/opt/astrbot/data/plugin_data/astrbot_plugin_memory_system/memory_system.db"


def scope_of(user_id: str) -> str:
    return f"aiocqhttp:FriendMessage:{user_id}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB)
    ap.add_argument("--jsonl", default="/tmp/questions.jsonl")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    eng = ShadowEngine(args.db)
    rows = [json.loads(l) for l in open(args.jsonl, encoding="utf-8") if l.strip()]
    if args.only:
        rows = [r for r in rows if r["id"] in args.only.split(",")]

    hit = miss = 0
    obs = 0
    print(f"{'id':5} {'cat':10} {'mode':9} {'cand':>4} {'got':<22} {'exp':<16} result")
    print("-" * 92)
    for r in rows:
        # 固定时钟：题集可指定 now_offset_days 把「现在」推进到未来某天，用于冷层用例
        now = time.time() + float(r.get("now_offset_days") or 0) * 86400.0
        res = eng.run(user_id=r["ask_user"], scope=scope_of(r["ask_user"]),
                      text=r["q"], write=False, now=now)
        got = [i["id"] for i in res["injected"]]
        exp = set(r.get("expect_ids") or [])
        ok = bool(set(got) & exp) or (not exp and not got)
        if r.get("observe"):
            obs += 1
            tag = "OBS"
        else:
            hit += 1 if ok else 0
            miss += 0 if ok else 1
            tag = "OK" if ok else "MISS"
        print(f"{r['id']:5} {r['cat']:10} {res['mode']:9} {res['candidates']:4d} "
              f"{str(got):<22} {str(sorted(exp)):<16} {tag}")
        if tag == "MISS":
            print(f"      q={r['q']}  note={r.get('note','')}")
            for i in res["injected"]:
                print(f"      - [{i['id']}] rel={i['rel']} score={i['score']} cold={i['cold']} {i['content']}")
    print("-" * 92)
    print(f"hit={hit} miss={miss} total={hit + miss} observe={obs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
