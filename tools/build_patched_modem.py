#!/usr/bin/env python3
"""
Build and cryptographically verify patched modem.b19, modem.b01, and modem.mdt
for Quectel EM060K-GL (EM060KGLAAR01A11M2G_01.202.01.202).

Supports two modes:
  - both (default): Unlocks both Russia (MCC 250) and Iran (MCC 432)
  - ru            : Unlocks Russia (MCC 250) only

Usage:
    python3 tools/build_patched_modem.py <stock_image_dir> <output_dir> [both|ru]
"""
import hashlib
import os
import subprocess
import sys
from q6zip_v32_decompress import B19_VA_BASE, decompress_page_v32, parse_b19_header

RU_PATCH_OFFSET = 0x15B595  # 0x40 -> 0x50 (VA 0xd021d654: 0x1048400c -> 0x1048500c)
IR_PATCH_OFFSET = 0x15BA67  # 0x78 -> 0x7a (VA 0xd021d674: 0x1048c20a -> 0x1048d20a)


def gen_rsa_key(exp_flag: str, key_path: str):
    if not os.path.exists(key_path):
        subprocess.run(
            ["openssl", "genrsa", exp_flag, "-out", key_path, "2048"],
            check=True,
            capture_output=True,
        )
    r_der = subprocess.run(
        ["openssl", "rsa", "-in", key_path, "-traditional", "-outform", "DER"],
        check=True,
        capture_output=True,
    )
    r_asn = subprocess.run(
        ["openssl", "asn1parse", "-inform", "DER"],
        input=r_der.stdout,
        check=True,
        capture_output=True,
    )
    ints = []
    for line in r_asn.stdout.decode().splitlines():
        if "INTEGER" in line:
            val_hex = line.split("INTEGER")[1].strip().lstrip(":")
            ints.append(int(val_hex, 16))
    n, e, d = ints[1], ints[2], ints[3]
    n_bytes = n.to_bytes(256, "big")
    assert n_bytes[0] & 0x80, "Modulus MSB not set"
    return n, e, d, n_bytes


def rsa_pkcs1_sha256_sign(tbs_bytes: bytes, n: int, d: int) -> bytes:
    digest = hashlib.sha256(tbs_bytes).digest()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + digest
    pad_len = 256 - 3 - len(digest_info)
    em = b"\x00\x01" + (b"\xff" * pad_len) + b"\x00" + digest_info
    sig_int = pow(int.from_bytes(em, "big"), d, n)
    return sig_int.to_bytes(256, "big")


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <stock_image_dir> <output_dir> [both|ru]", file=sys.stderr)
        sys.exit(1)

    img_dir = sys.argv[1]
    out_dir = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "both"
    os.makedirs(out_dir, exist_ok=True)

    b00 = open(os.path.join(img_dir, "modem.b00"), "rb").read()
    b01 = bytearray(open(os.path.join(img_dir, "modem.b01"), "rb").read())
    b19 = bytearray(open(os.path.join(img_dir, "modem.b19"), "rb").read())

    assert b19[RU_PATCH_OFFSET] == 0x40
    assert b19[IR_PATCH_OFFSET] == 0x78

    b19[RU_PATCH_OFFSET] = 0x50
    if mode == "both":
        b19[IR_PATCH_OFFSET] = 0x7A

    _, _, dict1, dict2, ptrs = parse_b19_header(b19)
    p541_start = ptrs[541] - B19_VA_BASE
    p541_end = ptrs[542] - B19_VA_BASE
    orig_b19_bytes = open(os.path.join(img_dir, "modem.b19"), "rb").read()
    orig_p541, _, _ = decompress_page_v32(orig_b19_bytes[p541_start:p541_end], dict1, dict2)
    new_p541, _, _ = decompress_page_v32(bytes(b19[p541_start:p541_end]), dict1, dict2)
    diffs = [(i, orig_p541[i], new_p541[i]) for i in range(1024) if orig_p541[i] != new_p541[i]]
    if mode == "both":
        assert diffs == [(405, 0x1048400C, 0x1048500C), (413, 0x1048C20A, 0x1048D20A)]
        print("[OK] Page 541 diff verified (Russia MCC 250 + Iran MCC 432 unlocked)")
    else:
        assert diffs == [(405, 0x1048400C, 0x1048500C)]
        print("[OK] Page 541 diff verified (Russia MCC 250 unlocked)")

    n2, e2, d2, n2_bytes = gen_rsa_key("-3", os.path.join(out_dir, "root_ca.key"))
    n1, e1, d1, n1_bytes = gen_rsa_key("-3", os.path.join(out_dir, "attest_ca.key"))
    n0, e0, d0, n0_bytes = gen_rsa_key("-f4", os.path.join(out_dir, "attest_leaf.key"))

    certs_blob = b01[1288 : 1288 + 6144]
    c0 = bytearray(certs_blob[0:1163])
    c1 = bytearray(certs_blob[1163 : 1163 + 986])
    c2 = bytearray(certs_blob[1163 + 986 : 1163 + 986 + 941])

    orig_n0_off = c0.find(bytes.fromhex("bb4d4816c21d3955"))
    orig_n1_off = c1.find(bytes.fromhex("d58189ce25afe14a"))
    orig_n2_off = c2.find(bytes.fromhex("b1d1a3752bf74823"))
    assert orig_n0_off == 541 and orig_n1_off == 353 and orig_n2_off == 344

    orig_ski2 = bytes.fromhex("5c3a1949a485efdee2169662449aa9cb0650b5d1")
    orig_ski1 = bytes.fromhex("4d1264a52d82e3e77bffae9c330b12757bf5bbbc")

    c2[orig_n2_off : orig_n2_off + 256] = n2_bytes
    new_ski2 = hashlib.sha1(c2[335:603]).digest()
    ski2_pos_in_c2 = c2.find(orig_ski2)
    c2[ski2_pos_in_c2 : ski2_pos_in_c2 + 20] = new_ski2
    c2[685:941] = rsa_pkcs1_sha256_sign(c2[4:665], n2, d2)

    c1[orig_n1_off : orig_n1_off + 256] = n1_bytes
    new_ski1 = hashlib.sha1(c1[344:612]).digest()
    aki2_pos_in_c1 = c1.find(orig_ski2)
    ski1_pos_in_c1 = c1.find(orig_ski1)
    c1[aki2_pos_in_c1 : aki2_pos_in_c1 + 20] = new_ski2
    c1[ski1_pos_in_c1 : ski1_pos_in_c1 + 20] = new_ski1
    c1[730:986] = rsa_pkcs1_sha256_sign(c1[4:710], n2, d2)

    c0[orig_n0_off : orig_n0_off + 256] = n0_bytes
    aki1_pos_in_c0 = c0.find(orig_ski1)
    c0[aki1_pos_in_c0 : aki1_pos_in_c0 + 20] = new_ski1
    c0[907:1163] = rsa_pkcs1_sha256_sign(c0[4:887], n1, d1)

    new_b19_hash = hashlib.sha256(b19).digest()
    b01[40 + 19 * 32 : 40 + 20 * 32] = new_b19_hash

    sw_id = (0x0000000000000002).to_bytes(8, "big")
    hw_id = (0x001890E100000000).to_bytes(8, "big")
    ipad = bytes(b ^ 0x36 for b in sw_id)
    opad = bytes(b ^ 0x5C for b in hw_id)
    h0 = hashlib.sha256(b01[:1032]).digest()
    qpsa_hash = hashlib.sha256(opad + hashlib.sha256(ipad + h0).digest()).digest()

    qpsa_em = b"\x00\x01" + (b"\xff" * 221) + b"\x00" + qpsa_hash
    qpsa_sig = pow(int.from_bytes(qpsa_em, "big"), d0, n0).to_bytes(256, "big")
    assert pow(int.from_bytes(qpsa_sig, "big"), e0, n0).to_bytes(256, "big") == qpsa_em
    print("[OK] QPSA RSA-2048 signature verified against Cert 0 public key")

    b01[1032:1288] = qpsa_sig
    new_certs_chain = bytes(c0) + bytes(c1) + bytes(c2)
    b01[1288 : 1288 + 3090] = new_certs_chain

    new_mdt = b00 + bytes(b01)
    open(os.path.join(out_dir, "modem.b19"), "wb").write(b19)
    open(os.path.join(out_dir, "modem.b01"), "wb").write(b01)
    open(os.path.join(out_dir, "modem.mdt"), "wb").write(new_mdt)
    for fn in ["modem.b19", "modem.b01", "modem.mdt"]:
        h = hashlib.sha256(open(os.path.join(out_dir, fn), "rb").read()).hexdigest()
        print(f"  {fn:10s}: sha256={h}")


if __name__ == "__main__":
    main()
