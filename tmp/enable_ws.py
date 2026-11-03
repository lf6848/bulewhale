import json, shutil, time
P = "/opt/astrbot/data/cmd_config.json"
shutil.copy(P, P + ".bak-ws-" + time.strftime("%Y%m%d-%H%M%S"))
c = json.load(open(P, encoding="utf-8-sig"))
ps = c["provider_settings"]
ps["web_search"] = True
ps["websearch_provider"] = "anysearch"
json.dump(c, open(P, "w", encoding="utf-8-sig"), ensure_ascii=False, indent=2)
print("web_search=", ps["web_search"], "provider=", ps["websearch_provider"])
