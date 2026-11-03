import json
import datetime
import sys

import jwt

cfg = json.load(open("/AstrBot/data/cmd_config.json", encoding="utf-8-sig"))
d = cfg["dashboard"]
payload = {
    "username": d["username"],
    "exp": datetime.datetime.now(datetime.timezone.utc)
    + datetime.timedelta(minutes=30),
}
print(jwt.encode(payload, d["jwt_secret"], algorithm="HS256"))
