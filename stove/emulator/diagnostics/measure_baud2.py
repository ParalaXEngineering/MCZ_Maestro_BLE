# Precise bit-period histogram of the panel's UART2 on GPIO5.
# Uses time_pulse_us (CPU cycle counter) so it's independent of the UART clock.
# The smallest well-populated pulse-width bucket = one bit period => true baud.
from machine import Pin
import machine
import time

p = Pin(5, Pin.IN, Pin.PULL_UP)
raw = []
t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < 6000 and len(raw) < 4000:
    w = machine.time_pulse_us(p, 0, 3000)   # low pulse
    if w > 0:
        raw.append(w)
    w = machine.time_pulse_us(p, 1, 3000)   # high pulse
    if w > 0:
        raw.append(w)

if not raw:
    print("no edges")
else:
    hist = {}
    for w in raw:
        if w <= 45:
            b = w  # 1us buckets
            hist[b] = hist.get(b, 0) + 1
    print("pulse-width histogram (us : count):")
    for k in sorted(hist):
        print("  %2d : %s" % (k, "#" * min(hist[k], 60) + (" %d" % hist[k])))
    raw.sort()
    # unit = smallest bucket with a meaningful count (>= 5% of max bucket)
    peak = max(hist.values())
    unit = min(k for k, c in hist.items() if c >= max(2, peak // 20))
    print("count=%d min=%d unit(bit)~=%dus => baud ~= %d"
          % (len(raw), raw[0], unit, int(1000000 / unit)))
    for b in (921600, 500000, 460800, 250000, 230400, 115200):
        print("   baud %-7d -> bit %.2f us" % (b, 1000000.0 / b))
