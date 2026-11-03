import hashlib, json, os, time

P = "/tmp/webui.json"
NEW = "Qjy_20060610"

with open(P, encoding="utf-8") as f:
    st = json.load(f)

salt_hex = os.urandom(16).hex()
h = hashlib.scrypt(NEW.encode(), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1, dklen=64).hex()

now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
st["passwordHash"] = h
st["passwordSalt"] = salt_hex
st["mustChangePassword"] = False
st["updatedAt"] = now

with open(P, "w", encoding="utf-8") as f:
    json.dump(st, f, ensure_ascii=False, indent=2)

print("ok mustChangePassword=", st["mustChangePassword"], "updatedAt=", now)
print("hashlen=", len(h), "saltlen=", len(salt_hex))
