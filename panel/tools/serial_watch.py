#!/usr/bin/env python3
"""Watch the ESP32 panel serial (COM38 @115200). Optionally reset the board first
(toggle EN via RTS) to reopen the BLE pairing window, then log for N seconds with
elapsed timestamps."""
import sys, time
import serial

# Usage: python serial_watch.py [seconds] [--reset] [--port COMxx]
#   panel (firmware/BLE) is on COM39 (antenna board) after the 2026-07-07 swap.
PORT = "COM39"
if "--port" in sys.argv:
    PORT = sys.argv[sys.argv.index("--port") + 1]
BAUD = 115200
_pos = [a for a in sys.argv[1:] if not a.startswith("--") and a != PORT]
DUR = float(_pos[0]) if _pos else 40.0
RESET = "--reset" in sys.argv

s = serial.Serial(PORT, BAUD, timeout=0.2)
if RESET:
    # ESP32 auto-reset: EN=RTS, GPIO0=DTR. Pulse EN low->high, keep GPIO0 high (run mode).
    s.setDTR(False)   # GPIO0 high -> normal boot
    s.setRTS(True)    # EN low -> in reset
    time.sleep(0.15)
    s.setRTS(False)   # EN high -> run
    print("[reset] board reset, pairing window reopened", flush=True)

t0 = time.time()
buf = b""
while time.time() - t0 < DUR:
    data = s.read(256)
    if data:
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            txt = line.decode("utf-8", "replace").rstrip("\r")
            print(f"[{time.time()-t0:6.1f}] {txt}", flush=True)
s.close()
print("[capture ended]", flush=True)
