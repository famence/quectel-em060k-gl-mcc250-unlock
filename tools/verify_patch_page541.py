#!/usr/bin/env python3
"""
Verify the 1-bit patches on Page 541 (0xd021d000) of modem.b19 in EM060KGLAAR01A11M2G_01.202.01.202
for both Russia (MCC 250) and Iran (MCC 432).

Usage:
    python3 tools/verify_patch_page541.py /path/to/stock/modem.b19
"""
import struct
import sys
from q6zip_v32_decompress import B19_VA_BASE, decompress_page_v32, parse_b19_header

RU_PATCH_OFFSET = 0x15B595  # LITERAL[110] byte 1: 0x40 -> 0x50 (VA 0xd021d654: 0x1048400c -> 0x1048500c)
IR_PATCH_OFFSET = 0x15BA67  # Bitstream bit 5241: 0x78 -> 0x7a (VA 0xd021d674: 0x1048c20a -> 0x1048d20a)


def sim_plmn_check(words_p541, packed_mcc: int) -> int:
    r16 = (packed_mcc >> 8) & 0xF
    r17 = (packed_mcc >> 4) & 0xF
    r18 = packed_mcc & 0xF
    u5_0 = (words_p541[403] >> 8) & 0x1F
    u5_1 = (words_p541[404] >> 8) & 0x1F
    u5_2 = (words_p541[405] >> 8) & 0x1F
    if r18 == u5_0 and r17 == u5_1 and r16 == u5_2:
        return 1
    u5_3 = (words_p541[411] >> 8) & 0x1F
    u5_4 = (words_p541[412] >> 8) & 0x1F
    u5_5 = (words_p541[413] >> 8) & 0x1F
    if r18 == u5_3 and r17 == u5_4 and r16 == u5_5:
        return 1
    return 0


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <stock_modem.b19>", file=sys.stderr)
        sys.exit(1)

    b19 = open(sys.argv[1], "rb").read()
    _, _, dict1, dict2, ptrs = parse_b19_header(b19)

    page_idx = 541
    start = ptrs[page_idx] - B19_VA_BASE
    end = ptrs[page_idx + 1] - B19_VA_BASE
    orig_page = bytearray(b19[start:end])
    orig_words, _, _ = decompress_page_v32(bytes(orig_page), dict1, dict2)

    assert b19[RU_PATCH_OFFSET] == 0x40
    assert b19[IR_PATCH_OFFSET] == 0x78

    # 1. Verify Russia + Iran unlock (MCC 250 + MCC 432)
    both_page = bytearray(orig_page)
    both_page[RU_PATCH_OFFSET - start] = 0x50
    both_page[IR_PATCH_OFFSET - start] = 0x7A
    both_words, _, _ = decompress_page_v32(bytes(both_page), dict1, dict2)

    diffs = [
        (i, orig_words[i], both_words[i])
        for i in range(1024)
        if orig_words[i] != both_words[i]
    ]
    print(f"[Russia + Iran] Page 541 decompressed diffs ({len(diffs)} words changed):")
    for i, ow, nw in diffs:
        print(f"  word {i} (VA 0x{0xD021D000 + i * 4:08x}): 0x{ow:08x} -> 0x{nw:08x}")
    assert diffs == [
        (405, 0x1048400C, 0x1048500C),  # Russia MCC 250: cmp.eq(r16, #0) -> cmp.eq(r16, #16)
        (413, 0x1048C20A, 0x1048D20A),  # Iran   MCC 432: cmp.eq(r16, #2) -> cmp.eq(r16, #18)
    ]

    changed = []
    for mcc in range(4096):
        old_res = sim_plmn_check(orig_words, mcc)
        new_res = sim_plmn_check(both_words, mcc)
        if old_res != new_res:
            changed.append((mcc, old_res, new_res))
    assert changed == [(0x052, 1, 0), (0x234, 1, 0)]
    print(
        "[OK] Exhaustive 4096-input check passed: ONLY MCC 250 (0x052) and MCC 432 (0x234) "
        "changed from 1 (forbidden) -> 0 (allowed). All 4096 MCCs now return 0 (allowed)."
    )


if __name__ == "__main__":
    main()
