# Wide sweep for panel UART2 (baud x invert), scored by CRC-valid Modbus frames.
# Also prints a raw sample so we can eyeball the frame structure. rx=5 (panel TX).
from machine import UART
import time


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def count_modbus(data):
    hits = 0
    samp = None
    for i in range(0, len(data) - 7):
        if data[i + 1] in (0x03, 0x06):
            if crc16(data[i:i + 6]) == (data[i + 6] | (data[i + 7] << 8)):
                hits += 1
                if samp is None:
                    samp = bytes(data[i:i + 8])
    return hits, samp


BAUDS = [460800, 500000, 576000, 614400, 750000, 921600,
         1000000, 1152000, 1500000, 2000000]

best = None
for baud in BAUDS:
    for inv, itag in ((0, "N"), (UART.INV_RX, "I")):
        u = UART(2, baudrate=baud, bits=8, parity=None, stop=1, tx=4, rx=5,
                 timeout=0, rxbuf=4096, invert=inv)
        buf = bytearray()
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 1400:
            n = u.any()
            if n:
                buf.extend(u.read(n))
        u.deinit()
        time.sleep_ms(20)
        hits, samp = count_modbus(buf)
        raw = bytes(buf[:36]).hex()
        tag = "  <<<< MODBUS" if hits else ""
        print("%-8d %s b=%3d mb=%d raw=%s%s" % (baud, itag, len(buf), hits, raw, tag))
        if hits and (best is None or hits > best[2]):
            best = (baud, itag, hits, samp)

print("BEST:", best if best else "none")
