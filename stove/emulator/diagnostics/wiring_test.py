#!/usr/bin/env python3
"""Decisive UART2 wiring test.

Hypothesis: COM39 (panel) UART2 is cross-wired to COM38 UART2. If so, COM38's
transmissions are what make the panel print 'Function Error'. Holding COM38 in
reset (silent) should make the panel fall back to only 'Timeout 1'.

Phase A (~4s): COM38 running  -> expect panel to show Function Error (+Timeout).
Phase B (~5s): COM38 held in reset -> expect panel to show ONLY Timeout 1.

Usage: python wiring_test.py
"""
import time
import serial

PANEL = "COM39"   # healthy panel, Modbus master on UART2
OTHER = "COM38"   # board whose UART2 is (hypothetically) wired to the panel


def open_running(port, baud):
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 0.05
    s.dtr = False   # GPIO0 high (normal boot)
    s.rts = False   # EN high (run)
    s.open()
    s.dtr = False
    s.rts = False
    return s


def watch(panel, secs, label):
    print(f"\n--- {label} ({secs}s) ---", flush=True)
    t0 = time.time()
    buf = b""
    seen = {}
    while time.time() - t0 < secs:
        data = panel.read(256)
        if data:
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                txt = line.decode("utf-8", "replace").rstrip("\r").strip()
                if not txt:
                    continue
                seen[txt] = seen.get(txt, 0) + 1
                print(f"[{time.time()-t0:5.1f}] {txt}", flush=True)
    return seen


def main():
    panel = open_running(PANEL, 115200)
    other = open_running(OTHER, 921600)  # opened running (rts=False)

    a = watch(panel, 4.0, "PHASE A: COM38 RUNNING")

    # Phase B: hold COM38 in reset (EN low), silencing it.
    other.rts = True
    print("\n>>> COM38 now HELD IN RESET (EN low) <<<", flush=True)
    b = watch(panel, 5.0, "PHASE B: COM38 HELD IN RESET")

    other.rts = False  # release
    panel.close()
    other.close()

    def n(d, key):
        return sum(v for k, v in d.items() if key.lower() in k.lower())

    print("\n===== RESULT =====")
    print(f"Phase A (COM38 running):  Function Error={n(a,'Function')}  Timeout={n(a,'Timeout')}")
    print(f"Phase B (COM38 in reset): Function Error={n(b,'Function')}  Timeout={n(b,'Timeout')}")
    if n(a, "Function") > 0 and n(b, "Function") == 0:
        print("=> CONFIRMED: COM38's UART2 transmissions cause the panel's 'Function Error'.")
        print("   The boards' UART2 are cross-wired. Fix = Modbus SLAVE firmware on COM38.")
    elif n(b, "Function") > 0:
        print("=> Panel still gets 'Function Error' with COM38 silent -> another source on panel RX.")
    else:
        print("=> Inconclusive (no Function Error seen in phase A). Re-run or check power.")


if __name__ == "__main__":
    main()
