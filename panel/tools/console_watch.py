#!/usr/bin/env python3
"""Read an ESP32 console at 115200 WITHOUT resetting it (dtr/rts left deasserted).
Usage: python console_watch.py [PORT] [SECONDS]"""
import sys
import time
import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM39"
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0

s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.2
s.dtr = False
s.rts = False
s.open()
s.dtr = False
s.rts = False

t0 = time.time()
buf = b""
while time.time() - t0 < DUR:
    d = s.read(256)
    if d:
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            print("[%6.1f] %s" % (time.time() - t0,
                                  line.decode("utf-8", "replace").rstrip("\r")), flush=True)
s.close()
