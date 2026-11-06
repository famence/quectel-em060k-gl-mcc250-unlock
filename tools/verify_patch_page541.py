#!/usr/bin/env python3
"""
Verify the 1-bit patch on Page 541 (0xd021d000) of modem.b19 in EM060KGLAAR01A11M2G_01.202.01.202.

Usage:
    python3 tools/verify_patch_page541.py /path/to/stock/modem.b19
"""
import struct
import sys
from q6zip_v32_decompress import B19_VA_BASE, decompress_page_v32, parse_b19_header


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

    patched_page = bytearray(orig_page)
    lit110_off = 0x15B594 - start
    orig_insn = struct.unpack_from("<I", patched_page, lit110_off)[0]
    assert orig_insn == 0x1048400C, f"Unexpected instruction: 0x{orig_insn:08x}"

    # Flip bit 12 (byte 0x15b595: 0x40 -> 0x50)
    patched_page[lit110_off + 1] = 0x50
    patched_words, _, _ = decompress_page_v32(bytes(patched_page), dict1, dict2)

    diffs = [
        (i, orig_words[i], patched_words[i])
        for i in range(1024)
        if orig_words[i] != patched_words[i]
    ]
    print(f"Page 541 decompressed diffs ({len(diffs)} word changed):")
    for i, ow, nw in diffs:
        print(f"  word {i} (VA 0x{0xD021D000 + i * 4:08x}): 0x{ow:08x} -> 0x{nw:08x}")
    assert diffs == [(405, 0x1048400C, 0x1048500C)]

    changed = []
    for mcc in range(4096):
        old_res = sim_plmn_check(orig_words, mcc)
        new_res = sim_plmn_check(patched_words, mcc)
        if old_res != new_res:
            changed.append((mcc, old_res, new_res))
    assert changed == [(0x052, 1, 0)]
    print("Exhaustive 4096-input check passed: ONLY MCC 250 (packed 0x052) changed from 1 (forbidden) -> 0 (allowed).")


if __name__ == "__main__":
    main()
