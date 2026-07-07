# Fine baud sweep (normal + inverted) scored by CRC-valid Modbus frames.
# Panel TX on GPIO5. Real bit period measured ~4.3us => focus 200k-300k, plus 2x/4x checks.
from machine import UART
import time


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def modbus_hits(data):
    hits, samp = 0, None
    for i in range(0, len(data) - 7):
        if data[i + 1] in (0x03, 0x06):
            if crc16(data[i:i + 6]) == (data[i + 6] | (data[i + 7] << 8)):
                hits += 1
                if samp is None:
                    samp = bytes(data[i:i + 8])
    return hits, samp


bauds = [38400, 56000, 57600, 62500, 76800, 100000, 111000, 115200, 117600,
         125000, 128000, 150000, 170000, 300000, 333333, 360000, 400000, 460800]

best = None
for baud in bauds:
    for inv, tag in ((0, "N"), (UART.INV_RX, "I")):
        try:
            u = UART(2, baudrate=baud, bits=8, parity=None, stop=1, tx=4, rx=5,
                     timeout=0, rxbuf=2048, invert=inv)
        except Exception as e:
            print(baud, tag, "err", e)
            continue
        buf = bytearray()
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 1400:
            n = u.any()
            if n:
                buf.extend(u.read(n))
        u.deinit()
        time.sleep_ms(20)
        hits, samp = modbus_hits(buf)
        # also try software bit-phase recovery on the framed byte stream
        slip_hit = 0
        if not hits and len(buf) > 10:
            bitstream = []
            for by in buf:
                for k in range(8):
                    bitstream.append((by >> k) & 1)
            for phase in range(1, 8):
                packed = bytearray()
                for j in range(phase, len(bitstream) - 8, 8):
                    v = 0
                    for k in range(8):
                        v |= bitstream[j + k] << k
                    packed.append(v)
                h2, _ = modbus_hits(packed)
                if h2:
                    slip_hit = h2
                    break
        if hits or slip_hit:
            print("%6d %s bytes=%3d hits=%d slip=%d raw=%s"
                  % (baud, tag, len(buf), hits, slip_hit, bytes(buf[:24]).hex()))
        if (hits or slip_hit) and (best is None or (hits + slip_hit) > best[0]):
            best = (hits + slip_hit, baud, tag, samp)

print("BEST:", best if best else "none")
