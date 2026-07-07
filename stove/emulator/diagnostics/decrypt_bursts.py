#!/usr/bin/env python3
"""Test whether the panel's UART2 bursts are AES-wrapped Modbus (same scheme as BLE)."""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY1 = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0 = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd345126" "39377b05a2510de725fc75")

BURSTS = [
    "7662d40de8c5654a1c21a859a629ca4523be10fbbdc29dd7da153c39176fcc66",
    "07e1acdeb742c27aed11eee4c07df58dc83c0dcb973a51802d8667c17a3b6e2d",
    "f389e0ceae7738c4ebc21f190b842b430c3cc04c77e8b2428498e423853d55eb",
    "54b04ee0975878706d95fbab02fddee6bba194a8d6afd71066506fe940bd9f44",
    "51f72361a7c232c40034b757efcf50b5ae3665cc52df23581a686a1faa60dd42",
    "4fdbbc45916e1dc464e33904fc4ea571e225b1685373e55bd9c03e65dda80d58",
]


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def dec_cbc(ct, key, iv):
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return d.update(ct) + d.finalize()


print("TOKEN =", TOKEN.hex(), "\n")
for i, h in enumerate(BURSTS):
    ct = bytes.fromhex(h)
    pt = dec_cbc(ct, KEY1, IV0)
    has_token = TOKEN in pt
    tok_at = pt.find(TOKEN)
    print("burst %d cbc-decrypt: %s" % (i, pt.hex()))
    print("   token present=%s at=%d" % (has_token, tok_at))
    if tok_at >= 0:
        after = pt[tok_at + 16:]
        print("   after-token (modbus?): %s" % after.hex())
    # also try ECB per-block and IV=0, in case scheme differs
