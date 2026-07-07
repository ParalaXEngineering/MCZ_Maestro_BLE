#!/usr/bin/env python3
"""Offline 'panel-side' verifier for a candidate mainboard reply frame.

Mirrors the checks the real panel firmware runs on a UART2 reply, so we can
validate the emulator's reply WITHOUT hardware:
  * ciphertext length must be a multiple of 16   (panel: "No x16 - %d")
  * AES-128-CBC(KEY1, IV0) decrypt
  * TOKEN must match                             (panel: token check / drop)
  * strip PKCS#7, split trailing CRC16           (panel: "CRC Err")
  * parse the 0x41 reply PDU and extract named registers

Use it two ways:
  panel_check.py hex <ciphertext_hex>
  panel_check.py build           # build+check a reply the SAME way the emulator does
"""
import sys, struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY1 = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0 = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd34512639377b05a2510de725fc75")

# request the panel actually sends
REQ_REG = 0x02BC
REQ_CNT = 0x012C  # 300


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def enc(pt):
    e = Cipher(algorithms.AES(KEY1), modes.CBC(IV0)).encryptor()
    return e.update(pt) + e.finalize()


def dec(ct):
    d = Cipher(algorithms.AES(KEY1), modes.CBC(IV0)).decryptor()
    return d.update(ct) + d.finalize()


def wrap(counter, pdu):
    body = counter.to_bytes(4, "little") + TOKEN + pdu
    c = crc16(pdu)
    body += bytes((c & 0xFF, (c >> 8) & 0xFF))
    pad = 16 - (len(body) % 16)
    body += bytes((pad,)) * pad
    return enc(body)


def check(ct, req_reg=REQ_REG, want_regs=(0x02C9, 0x0320, 0x0322)):
    print("ciphertext len = %d bytes  (%% 16 == %d -> %s)"
          % (len(ct), len(ct) % 16, "OK" if len(ct) % 16 == 0 else "PANEL: 'No x16'"))
    if len(ct) % 16 or len(ct) < 32:
        return False
    pt = dec(ct)
    ctr = int.from_bytes(pt[0:4], "little")
    tok_ok = pt[4:20] == TOKEN
    print("counter = 0x%08x   token %s" % (ctr, "OK" if tok_ok else "MISMATCH -> dropped"))
    if not tok_ok:
        return False
    body = pt[20:]
    pad = body[-1]
    if not (1 <= pad <= 16) or any(x != pad for x in body[-pad:]):
        print("PKCS#7 pad invalid (last=%d)" % pad)
        return False
    body = body[:-pad]
    pdu, rxcrc = body[:-2], body[-2] | (body[-1] << 8)
    crc_ok = crc16(pdu) == rxcrc
    print("PDU (%d B) = %s" % (len(pdu), pdu.hex()))
    print("CRC %s (calc=0x%04x rx=0x%04x)" % ("OK" if crc_ok else "PANEL: 'CRC Err'", crc16(pdu), rxcrc))
    if not crc_ok:
        return False
    addr, func = pdu[0], pdu[1]
    print("addr=0x%02x func=0x%02x" % (addr, func))
    data = pdu[2:]  # assume [addr func <register words...>] layout (no byte-count header for 0x41)
    nregs = len(data) // 2
    print("carries %d register words -> covers 0x%04x .. 0x%04x"
          % (nregs, req_reg, req_reg + nregs - 1))
    for r in want_regs:
        idx = r - req_reg
        if 0 <= idx < nregs:
            v = (data[idx * 2] << 8) | data[idx * 2 + 1]
            print("  reg 0x%04x @word %d = 0x%04x (%d)" % (r, idx, v, v))
        else:
            print("  reg 0x%04x NOT in reply (word idx %d, need >= %d words)" % (r, idx, idx + 1))
    return True


def build_like_emulator():
    """Replicate stove/emulator/emulator_main.py build_response for func 0x41."""
    reg, cnt = REQ_REG, REQ_CNT
    n = min(cnt, 20)
    regmap = {
        0x02BC: 210, 0x02C1: 250, 0x02C5: 450, 0x02C9: 1,
        0x02CE: 1500, 0x02D1: 1200,
        0x0320: 0x0202, 0x0322: 3, 0x0324: 3, 0x032E: 1, 0x0332: 0,
        0x0334: 5, 0x0340: 1000,
    }
    data = bytearray()
    for i in range(n):
        v = regmap.get(reg + i, 0)
        data += bytes(((v >> 8) & 0xFF, v & 0xFF))
    pdu = bytes((0x01, 0x41)) + bytes(data)
    return wrap(0x1234, pdu)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "hex":
        check(bytes.fromhex(sys.argv[2]))
    else:
        print("== current emulator reply (n=min(cnt,20)=20 registers) ==")
        check(build_like_emulator())
