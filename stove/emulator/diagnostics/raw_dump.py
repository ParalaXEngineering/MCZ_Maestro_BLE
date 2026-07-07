# Clean raw capture of panel UART2 at 115200 8N1 (rx=5). Dump each ~1/s burst as
# hex + ASCII, and try to locate Modbus-RTU frames (any slave addr, func 3/6/16).
from machine import UART
import time


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


u = UART(2, baudrate=115200, bits=8, parity=None, stop=1, tx=4, rx=5,
         timeout=0, rxbuf=4096)

frames = []
cur = bytearray()
last = t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < 7000 and len(frames) < 6:
    n = u.any()
    now = time.ticks_ms()
    if n:
        cur.extend(u.read(n))
        last = now
    elif cur and time.ticks_diff(now, last) > 20:
        frames.append(bytes(cur))
        cur = bytearray()
if cur:
    frames.append(bytes(cur))
u.deinit()

for i, f in enumerate(frames):
    ascii_r = "".join(chr(b) if 32 <= b < 127 else "." for b in f)
    print("burst %d (%dB): %s" % (i, len(f), f.hex()))
    print("        ascii: %r" % ascii_r)
    # scan for CRC-valid modbus frames of common lengths
    for L in (8, 7, 6, 5):
        for j in range(0, len(f) - L + 1):
            body, crc = f[j:j + L - 2], f[j + L - 2] | (f[j + L - 1] << 8)
            if len(body) >= 2 and body[1] in (0x03, 0x04, 0x06, 0x10) and crc16(body) == crc:
                print("        modbus@%d len=%d: %s (crc ok)" % (j, L, f[j:j + L].hex()))
