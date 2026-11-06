#!/usr/bin/env python3
"""
Compute Quectel AT+QADBKEY unlock key from the 8-digit challenge returned by AT+QADBKEY?.

Usage:
    python3 tools/qadbkey.py 10244048
"""
import hashlib
import sys


def compute_qadbkey(challenge: str, secret: str = "SH_adb_quectel") -> str:
    pw = secret.encode("ascii")
    salt = challenge.strip().encode("ascii")[:8]
    magic = b"$1$"

    alt = hashlib.md5(pw + salt + pw).digest()
    ctx = hashlib.md5(pw + magic + salt)
    pl = len(pw)
    while pl > 0:
        ctx.update(alt[:16] if pl > 16 else alt[:pl])
        pl -= 16

    i = len(pw)
    while i > 0:
        ctx.update(b"\x00" if (i & 1) else pw[:1])
        i >>= 1
    final = ctx.digest()

    for idx in range(1000):
        c1 = hashlib.md5()
        c1.update(pw if (idx & 1) else final)
        if idx % 3 != 0:
            c1.update(salt)
        if idx % 7 != 0:
            c1.update(pw)
        c1.update(final if (idx & 1) else pw)
        final = c1.digest()

    itoa64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = []

    def to64(v: int, n: int):
        for _ in range(n):
            out.append(itoa64[v & 0x3F])
            v >>= 6

    to64((final[0] << 16) | (final[6] << 8) | final[12], 4)
    to64((final[1] << 16) | (final[7] << 8) | final[13], 4)
    to64((final[2] << 16) | (final[8] << 8) | final[14], 4)
    to64((final[3] << 16) | (final[9] << 8) | final[15], 4)
    to64((final[4] << 16) | (final[10] << 8) | final[5], 4)
    to64(final[11], 2)

    return "".join(out)[:15]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <challenge>", file=sys.stderr)
        sys.exit(1)
    key = compute_qadbkey(sys.argv[1])
    print(f"Challenge : {sys.argv[1].strip()}")
    print(f"QADBKEY   : {key}")
    print(f'AT Command: AT+QADBKEY="{key}"')
