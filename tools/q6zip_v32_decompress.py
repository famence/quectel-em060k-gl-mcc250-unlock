#!/usr/bin/env python3
"""
Qualcomm q6zip v3.2 decompressor for Quectel EM060K-GL (SDX12) modem.b19.

Usage:
    python3 tools/q6zip_v32_decompress.py /path/to/modem.b19 /path/to/b19_decompressed.bin
"""
import struct
import sys
import time

OP_BITS = [3, 3, 4, 3, 3, 4, 3, 3, 3, 3, 4, 3, 3, 4, 3, 3]
B19_VA_BASE = 0xC4B10000


def parse_b19_header(b19: bytes):
    npages, version = struct.unpack_from("<HH", b19, 0)
    dict1 = struct.unpack_from("<1024I", b19, 4)
    dict2 = struct.unpack_from("<4096I", b19, 4 + 4096)
    ptrs = struct.unpack_from(f"<{npages}I", b19, 4 + 4096 + 16384)
    return npages, version, dict1, dict2, ptrs


def decompress_page_v32(page_bytes: bytes, dict1, dict2):
    if len(page_bytes) == 4:
        (val,) = struct.unpack("<I", page_bytes)
        return [val] * 1024, 0, 0

    (w0,) = struct.unpack_from("<I", page_bytes, 0)
    literals = struct.unpack_from(f"<{w0}I", page_bytes, 4)
    lit_idx = 0

    bs_padded = page_bytes[(1 + w0) * 4 :] + b"\x00" * 32

    def get_bits64(bit_pos: int) -> int:
        byte_idx = bit_pos >> 3
        bit_off = bit_pos & 7
        w_lo, w_hi = struct.unpack_from("<QI", bs_padded, byte_idx)
        return ((w_lo | (w_hi << 64)) >> bit_off) & 0xFFFFFFFFFFFFFFFF

    op_cur = get_bits64(0) & 0xF
    r7 = OP_BITS[op_cur]
    op_next = get_bits64(r7) & 0xF
    r7 += OP_BITS[op_next]
    r25 = -1
    out = [0] * 1024

    for step in range(1024):
        cur = get_bits64(r7)
        op4 = op_cur
        op3 = op4 & 0x7

        if op4 == 0b0101:
            idx12 = cur & 0xFFF
            op_next2 = (cur >> 12) & 0xF
            r7 += 12
            r5 = dict2[idx12]
        elif op3 == 0b100:
            idx10 = cur & 0x3FF
            op_next2 = (cur >> 10) & 0xF
            r7 += 10
            r5 = dict1[idx10]
        elif op3 == 0b011:
            op_next2 = cur & 0xF
            r5 = literals[lit_idx]
            lit_idx += 1
        elif op3 == 0b001:
            off9 = cur & 0x1FF
            op_next2 = (cur >> 9) & 0xF
            r7 += 9
            r25 = off9 - 512
            r5 = out[step + r25]
        elif op3 == 0b111:
            op_next2 = cur & 0xF
            r5 = out[step + r25]
        elif op3 == 0b000:
            off9 = cur & 0x1FF
            val8 = (cur >> 9) & 0xFF
            op_next2 = (cur >> 17) & 0xF
            r7 += 17
            r25 = off9 - 512
            r5 = (out[step + r25] & 0xFFFFFF00) | val8
        elif op4 == 0b0010:
            off9 = cur & 0x1FF
            val12 = (cur >> 9) & 0xFFF
            op_next2 = (cur >> 21) & 0xF
            r7 += 21
            r25 = off9 - 512
            r5 = (out[step + r25] & 0xFFFFF000) | val12
        elif op3 == 0b110:
            val8 = cur & 0xFF
            op_next2 = (cur >> 8) & 0xF
            r7 += 8
            r5 = (out[step + r25] & 0xFFFFFF00) | val8
        elif op4 == 0b1101:
            sub1 = cur & 1
            cur1 = cur >> 1
            if sub1 == 0:
                off9 = cur1 & 0x1FF
                val16 = (cur1 >> 9) & 0xFFFF
                op_next2 = (cur1 >> 25) & 0xF
                r7 += 26
                r25 = off9 - 512
                r5 = (out[step + r25] & 0xFFFF0000) | val16
            else:
                val12 = cur1 & 0xFFF
                op_next2 = (cur1 >> 12) & 0xF
                r7 += 13
                r5 = (out[step + r25] & 0xFFFFF000) | val12
        elif op4 == 0b1010:
            sub2 = cur & 3
            cur2 = cur >> 2
            if sub2 == 0:
                val16 = cur2 & 0xFFFF
                op_next2 = (cur2 >> 16) & 0xF
                r7 += 18
                r5 = (out[step + r25] & 0xFFFF0000) | val16
            elif sub2 == 3:
                off9 = cur2 & 0x1FF
                val8 = (cur2 >> 9) & 0xFF
                op_next2 = (cur2 >> 17) & 0xF
                r7 += 19
                r25 = off9 - 512
                r5 = (out[step + r25] & 0xFFFF00FF) | (val8 << 8)
            elif sub2 == 2:
                off9 = cur2 & 0x1FF
                val8 = (cur2 >> 9) & 0xFF
                op_next2 = (cur2 >> 17) & 0xF
                r7 += 19
                r25 = off9 - 512
                r5 = (out[step + r25] & 0xFF00FFFF) | (val8 << 16)
            else:
                sub1 = cur2 & 1
                cur3 = cur2 >> 1
                val8 = cur3 & 0xFF
                op_next2 = (cur3 >> 8) & 0xF
                r7 += 11
                if sub1 == 1:
                    r5 = (out[step + r25] & 0xFFFF00FF) | (val8 << 8)
                else:
                    r5 = (out[step + r25] & 0xFF00FFFF) | (val8 << 16)

        out[step] = r5
        op_cur = op_next
        op_next = op_next2
        r7 += OP_BITS[op_next]

    return out, lit_idx, w0


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <modem.b19> <output_decompressed.bin>", file=sys.stderr)
        sys.exit(1)

    b19 = open(sys.argv[1], "rb").read()
    npages, version, dict1, dict2, ptrs = parse_b19_header(b19)
    print(f"Loaded {sys.argv[1]}: {npages} pages, q6zip version 0x{version:04x}")

    t0 = time.time()
    with open(sys.argv[2], "wb") as f:
        bad_lit = 0
        for p in range(npages):
            start = ptrs[p] - B19_VA_BASE
            end = (ptrs[p + 1] - B19_VA_BASE) if p + 1 < npages else 0x831310
            words, lit_used, w0 = decompress_page_v32(b19[start:end], dict1, dict2)
            if w0 > 0 and not (w0 - 1 <= lit_used <= w0):
                bad_lit += 1
            f.write(struct.pack("<1024I", *words))
            if (p + 1) % 500 == 0 or p == npages - 1:
                print(f"Decompressed {p+1}/{npages} pages ({time.time()-t0:.1f}s), bad_lit={bad_lit}")


if __name__ == "__main__":
    main()
