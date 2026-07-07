# Is the panel's UART2 continuous or bursty? Timestamp when bytes arrive on GPIO5
# and group into bursts (new burst if idle > 30 ms). Baud is irrelevant here -
# we only care WHEN data is present, not its content.
from machine import UART
import time

u = UART(2, baudrate=115200, bits=8, parity=None, stop=1, tx=4, rx=5,
         timeout=0, rxbuf=4096)
arr = []  # (t_ms, nbytes)
t0 = time.ticks_ms()
while time.ticks_diff(time.ticks_ms(), t0) < 8000:
    n = u.any()
    if n:
        u.read(n)
        arr.append((time.ticks_diff(time.ticks_ms(), t0), n))
u.deinit()

# group into bursts
bursts = []
cur_start = cur_end = None
cur_bytes = 0
for t, n in arr:
    if cur_start is None:
        cur_start, cur_end, cur_bytes = t, t, n
    elif t - cur_end > 30:
        bursts.append((cur_start, cur_end, cur_bytes))
        cur_start, cur_end, cur_bytes = t, t, n
    else:
        cur_end, cur_bytes = t, cur_bytes + n
if cur_start is not None:
    bursts.append((cur_start, cur_end, cur_bytes))

print("window=8000ms  total_bytes=%d  bursts=%d" % (sum(n for _, n in arr), len(bursts)))
prev = None
for s, e, b in bursts:
    gap = "" if prev is None else "  gap_since_prev=%dms" % (s - prev)
    print("  burst @%4dms  dur=%3dms  bytes=%3d%s" % (s, e - s, b, gap))
    prev = s
if len(bursts) >= 2:
    gaps = [bursts[i][0] - bursts[i - 1][0] for i in range(1, len(bursts))]
    print("mean inter-burst interval = %d ms" % (sum(gaps) // len(gaps)))
