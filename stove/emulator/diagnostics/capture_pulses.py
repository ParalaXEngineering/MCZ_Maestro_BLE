# Capture the raw edge-timing train of the panel's UART2 on GPIO5, then print it
# as signed microsecond widths (positive=HIGH pulse, negative=LOW pulse, 0=idle gap).
# Decoded offline on the laptop against candidate bit periods -> true baud+bits.
from machine import Pin
import machine
import time

p = Pin(5, Pin.IN, Pin.PULL_UP)
seq = []
level = p.value()
t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < 5000 and len(seq) < 1200:
    w = machine.time_pulse_us(p, level, 2000)
    if w > 0:
        seq.append(w if level else -w)
        level ^= 1
    else:
        if seq and seq[-1] != 0:
            seq.append(0)   # idle gap marker
        level = p.value()

print("PULSES_BEGIN")
# chunk to keep lines short
line = []
for v in seq:
    line.append(str(v))
    if len(line) >= 40:
        print(",".join(line))
        line = []
if line:
    print(",".join(line))
print("PULSES_END n=%d" % len(seq))
