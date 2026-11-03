import hashlib

TARGET = "73f891bdb6f1e6cbaab1826e7756f0a4ec4d5400d206d23bd22989e94456767eeec72254f683272a5c8d0b4ac63eeee261a42b5acd936596215c1199a65ea8c2"
SALT_HEX = "79311b6e1ce98ec381c43a26bba50231"
pwd = b"41dfbe8f197eafc8"

for name, salt in (("hexstr", SALT_HEX.encode()), ("bytes", bytes.fromhex(SALT_HEX))):
    h = hashlib.scrypt(pwd, salt=salt, n=16384, r=8, p=1, dklen=64).hex()
    print(name, "MATCH" if h == TARGET else "no", h[:20])
