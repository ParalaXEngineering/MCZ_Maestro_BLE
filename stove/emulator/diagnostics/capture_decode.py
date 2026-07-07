# Capture panel UART2 bursts at 115200, decrypt on-device (AES-128-CBC, KEY1/IV0),
# parse the Modbus PDU, and enumerate distinct request types. Confirms MicroPython
# cryptolib works (needed for the emulator's live responses).
from machine import UART
import time
try:
    from cryptolib import aes
except ImportError:
    from ucryptolib import aes

KEY1 = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0 = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd34512639377b05a2510de725fc75")


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def decrypt(ct):
    return aes(KEY1, 2, IV0).decrypt(ct)


u = UART(2, baudrate=115200, bits=8, parity=None, stop=1, tx=4, rx=5,
         timeout=0, rxbuf=4096)
seen = {}
cur = bytearray()
last = t0 = time.ticks_ms()
n_ok = 0
while time.ticks_diff(time.ticks_ms(), t0) < 14000 and len(seen) < 40:
    n = u.any()
    now = time.ticks_ms()
    if n:
        cur.extend(u.read(n))
        last = now
    elif cur and time.ticks_diff(now, last) > 20:
        f = bytes(cur)
        cur = bytearray()
        if len(f) % 16 == 0 and len(f) >= 32:
            pt = decrypt(f)
            if pt[4:20] == TOKEN:
                n_ok += 1
                ctr = int.from_bytes(pt[0:4], "little")
                body = pt[20:]
                # strip PKCS7 pad
                pad = body[-1]
                if 1 <= pad <= 16:
                    body = body[:-pad]
                pdu, rxcrc = body[:-2], body[-2] | (body[-1] << 8)
                ok = crc16(pdu) == rxcrc
                addr, func = pdu[0], pdu[1]
                reg = (pdu[2] << 8) | pdu[3] if len(pdu) >= 4 else -1
                key = (func, reg)
                if key not in seen:
                    seen[key] = (ctr, pdu.hex(), ok)
                    print("NEW ctr=%d addr=%02x func=0x%02x reg=0x%04x pdu=%s crc=%s"
                          % (ctr, addr, func, reg, pdu.hex(), ok))

u.deinit()
print("\ndecoded_ok=%d distinct=%d" % (n_ok, len(seen)))
for (func, reg), (ctr, pdu, ok) in sorted(seen.items()):
    print("  func=0x%02x reg=0x%04x  pdu=%s" % (func, reg, pdu))
