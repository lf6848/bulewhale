import hashlib, json

TARGET = "73f891bdb6f1e6cbaab1826e7756f0a4ec4d5400d206d23bd22989e94456767eeec72254f683272a5c8d0b4ac63eeee261a42b5acd936596215c1199a65ea8c2"
SALT_HEX = "79311b6e1ce98ec381c43a26bba50231"
salt = bytes.fromhex(SALT_HEX)
pwd = b"41dda41bc30facaf"

cands = {}
cands["sha256(p+salt)"] = hashlib.sha256(pwd + salt).hexdigest()
cands["sha256(salt+p)"] = hashlib.sha256(salt + pwd).hexdigest()
cands["sha256(salt+':'+p)"] = hashlib.sha256(salt + b":" + pwd).hexdigest()
for it in (1000, 10000, 100000, 310000):
    cands[f"pbkdf2_{it}"] = hashlib.pbkdf2_hmac("sha256", pwd, salt, it, 32).hex()
for n in (16384, 32768):
    try:
        cands[f"scrypt_n{n}"] = hashlib.scrypt(pwd, salt=salt, n=n, r=8, p=1, dklen=32).hex()
    except Exception as e:
        pass
try:
    cands["scrypt_n16384_64"] = hashlib.scrypt(pwd, salt=SALT_HEX.encode(), n=16384, r=8, p=1, dklen=32).hex()
except Exception:
    pass

hit = [k for k, v in cands.items() if v == TARGET]
print("target len:", len(TARGET))
print("matched:", hit if hit else "NONE")
for k, v in cands.items():
    print(k, v[:24])
