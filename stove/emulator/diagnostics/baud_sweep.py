#!/usr/bin/env python3
"""Find the real baud/logic of the panel's UART2 by brute force.

For each candidate baud, capture a couple seconds, then slide a Modbus-RTU CRC
check across the byte stream under three bit transforms (identity / invert /
bit-reverse). A CRC-valid 01 03.. or 01 06.. frame is a near-certain lock
(false-positive ~1/65536). Also reports printable-ASCII ratio as a fallback.

Usage: python baud_sweep.py [PORT] [SECS_PER_BAUD]
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM38"
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

BAUDS = [9600, 19200, 38400, 57600, 74880, 115200, 128000, 230400,
         250000, 256000, 460800, 500000, 921600, 1000000, 1152000, 1500000]

_REV = [int(f"{i:08b}"[::-1], 2) for i in range(256)]


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def count_modbus(data: bytes) -> int:
    """Count CRC-valid 8-byte Modbus read/write frames anywhere in the stream."""
    hits = 0
    n = len(data)
    for i in range(0, n - 7):
        if data[i] == 0x01 and data[i + 1] in (0x03, 0x06):
            body = data[i:i + 6]
            crc_rx = data[i + 6] | (data[i + 7] << 8)
            if crc16(body) == crc_rx:
                hits += 1
    return hits


def printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    p = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return p / len(data)


def transforms(data: bytes):
    yield "identity", data
    yield "invert", bytes(b ^ 0xFF for b in data)
    yield "bitrev", bytes(_REV[b] for b in data)


def capture(baud: float) -> bytes:
    ser = serial.Serial()
    ser.port = PORT
    ser.baudrate = int(baud)
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    try:
        ser.open()
    except Exception as e:
        print(f"  {baud}: open failed: {e}")
        return b""
    ser.dtr = False
    ser.rts = False
    ser.reset_input_buffer()
    t0 = time.time()
    buf = bytearray()
    while time.time() - t0 < SECS:
        buf.extend(ser.read(4096))
    ser.close()
    return bytes(buf)


def main():
    print(f"Baud sweep on {PORT}, {SECS}s each. Looking for CRC-valid Modbus frames.\n")
    results = []
    for baud in BAUDS:
        data = capture(baud)
        best_mb = 0
        best_xf = None
        for name, xf in transforms(data):
            mb = count_modbus(xf)
            if mb > best_mb:
                best_mb, best_xf = mb, name
        pr = printable_ratio(data)
        results.append((best_mb, baud, best_xf, pr, len(data), data[:24]))
        flag = "  <<< MODBUS!" if best_mb else ""
        print(f"  baud={baud:>8}  bytes={len(data):>6}  modbus={best_mb:>3}"
              f" ({best_xf})  ascii={pr:4.0%}{flag}")

    print("\n--- summary (best first) ---")
    results.sort(key=lambda r: (r[0], r[3]), reverse=True)
    for mb, baud, xf, pr, n, sample in results[:5]:
        print(f"baud={baud} modbus={mb} xform={xf} ascii={pr:.0%}"
              f" sample={sample.hex(' ')}")
    top = results[0]
    if top[0]:
        print(f"\nLIKELY: {top[1]} baud, transform={top[2]} "
              f"({top[0]} valid Modbus frames)")
    else:
        print("\nNo CRC-valid Modbus frame at any baud. See ascii ratios above.")


if __name__ == "__main__":
    main()
