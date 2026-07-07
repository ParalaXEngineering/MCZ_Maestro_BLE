#!/usr/bin/env python3
"""Passive sniffer for the panel's UART2 (Modbus master) traffic.

Opens a serial port, listens for a few seconds, and hexdumps whatever the panel
sends. Used to learn the exact func-0x03 read / func-0x06 write requests the
panel emits at boot so the mainboard emulator can answer them.

Usage: python uart2_sniff.py [PORT] [BAUD] [SECONDS]
Defaults: COM38 921600 6
"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM38"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 921600
SECS = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
# "hold" = assert RTS to keep a local ESP32's EN low (silence its own console),
# so anything we read must be arriving from an external source on the RX line.
HOLD_RESET = "hold" in sys.argv[4:]


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def try_parse(frame: bytes):
    """Best-effort decode of a Modbus-RTU frame."""
    if len(frame) < 4:
        return None
    body, crc_rx = frame[:-2], int.from_bytes(frame[-2:], "little")
    ok = crc16(body) == crc_rx
    slave, func = frame[0], frame[1]
    info = f"slave=0x{slave:02x} func=0x{func:02x}"
    if func == 0x03 and len(frame) == 8:
        reg = int.from_bytes(frame[2:4], "big")
        cnt = int.from_bytes(frame[4:6], "big")
        info += f" READ reg=0x{reg:04x} cnt=0x{cnt:04x} ({cnt})"
    elif func == 0x06 and len(frame) == 8:
        reg = int.from_bytes(frame[2:4], "big")
        val = int.from_bytes(frame[4:6], "big")
        info += f" WRITE reg=0x{reg:04x} val=0x{val:04x} ({val})"
    info += "  CRC " + ("OK" if ok else "BAD")
    return info


def main():
    print(f"Sniffing {PORT} @ {BAUD} 8N1 for {SECS}s ...", flush=True)
    ser = serial.Serial()
    ser.port = PORT
    ser.baudrate = BAUD
    ser.timeout = 0.05
    ser.dtr = False
    # RTS drives EN on an ESP32 devboard: True => held in reset (silent).
    ser.rts = HOLD_RESET
    ser.open()
    ser.dtr = False
    ser.rts = HOLD_RESET
    if HOLD_RESET:
        print("(holding local ESP32 in reset via RTS)")

    t0 = time.time()
    buf = bytearray()
    last_rx = None
    total = 0
    while time.time() - t0 < SECS:
        chunk = ser.read(256)
        now = time.time()
        if chunk:
            total += len(chunk)
            # A gap > 3ms at 921600 marks a frame boundary (RTU t3.5 ~ 40us,
            # but USB batching is coarse; treat a lull as end-of-frame).
            if last_rx is not None and (now - last_rx) > 0.010 and buf:
                emit(bytes(buf), now - t0)
                buf = bytearray()
            buf.extend(chunk)
            last_rx = now
        else:
            if buf and last_rx is not None and (now - last_rx) > 0.010:
                emit(bytes(buf), now - t0)
                buf = bytearray()
    if buf:
        emit(bytes(buf), time.time() - t0)
    ser.close()
    print(f"\nTotal bytes received: {total}")
    if total == 0:
        print("NO DATA. Wiring or baud is wrong, or panel not driving UART2.")


def emit(frame: bytes, t: float):
    hexs = frame.hex(" ")
    ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in frame)
    print(f"[{t:6.2f}s] ({len(frame):3d}B) {hexs}", flush=True)
    print(f"          ascii: {ascii_repr!r}", flush=True)
    parsed = try_parse(frame)
    if parsed:
        print(f"          -> {parsed}", flush=True)


if __name__ == "__main__":
    main()
