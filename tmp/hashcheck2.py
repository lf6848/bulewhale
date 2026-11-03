import hashlib

TARGET = "73f891bdb6f1e6cbaab1826e7756f0a4ec4d5400d206d23bd22989e94456767eeec72254f683272a5c8d0b4ac63eeee261a42b5acd936596215c1199a65ea8c2"
SALT_HEX = "79311b6e1ce98ec381c43a26bba50231"
salt_b = bytes.fromhex(SALT_HEX)
pwd = b"41dda41bc30facaf"

cands = {}
for n in (16384, 32768, 1024):
    for r in (8,):
        for pp in (1,):
            try:
                cands[f"scrypt_n{n}_r{r}_p{pp}_d64_hexsalt"] = hashlib.scrypt(pwd, salt=SALT_HEX.encode(), n=n, r=r, p=pp, dklen=64).hex()
            except Exception:
                pass
            try:
                cands[f"scrypt_n{n}_r{r}_p{pp}_d64_bytes"] = hashlib.scrypt(pwd, salt=salt_b, n=n, r=r, p=pp, dklen=64).hex()
            except Exception:
                pass
for it in (100000, 210000, 600000):
    cands[f"pbkdf2_{it}_d64"] = hashlib.pbkdf2_hmac("sha256", pwd, salt_b, it, 64).hex()
cands["sha512(p+salt)"] = hashlib.sha512(pwd + salt_b).hexdigest()

hit = [k for k, v in cands.items() if v == TARGET]
print("matched:", hit if hit else "NONE")
print("tried:", len(cands))
