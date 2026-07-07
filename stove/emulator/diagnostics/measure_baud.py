# Measure the true baud of the panel's UART2 by timing pulse widths on GPIO5.
# The shortest low/high pulse ~= one bit period. baud = 1e6 / bit_us.
from machine import Pin
import machine
import time

p = Pin(5, Pin.IN, Pin.PULL_UP)
widths = []
t0 = time.ticks_ms()
# Sample for ~4s; most calls time out between the panel's ~1/s request bursts,
# but during a burst we capture many short pulses.
while time.ticks_diff(time.ticks_ms(), t0) < 4000 and len(widths) < 2000:
    w = machine.time_pulse_us(p, 0, 5000)   # width of next LOW pulse
    if w > 0:
        widths.append(w)
    w = machine.time_pulse_us(p, 1, 5000)   # width of next HIGH pulse
    if w > 0:
        widths.append(w)

if not widths:
    print("NO EDGES on GPIO5 - line idle/quiet during sample window")
else:
    widths.sort()
    mn = widths[0]
    print("edges=%d  min=%dus  p05=%dus  median=%dus  max=%dus"
          % (len(widths), mn, widths[len(widths) // 20], widths[len(widths) // 2], widths[-1]))
    print("smallest 12 us:", widths[:12])
    for name, b in (("921600", 921600), ("460800", 460800), ("230400", 230400),
                    ("115200", 115200), ("57600", 57600), ("38400", 38400),
                    ("19200", 19200), ("9600", 9600)):
        bit_us = 1000000.0 / b
        print("  if baud=%-7s bit=%.2fus" % (name, bit_us))
    print("=> implied baud ~= %d" % int(1000000.0 / mn))
