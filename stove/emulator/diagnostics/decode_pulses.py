#!/usr/bin/env python3
"""Offline UART decode of a captured edge-timing train (pulses_capture.txt).

Signed us widths: +high, -low, 0 = idle gap (burst boundary). Idle level = high.
Sweep bit period T and bit order / inversion; score by CRC-valid Modbus frames.
"""
import re

RAW = open("pulses_capture.txt").read()
nums = []
for line in RAW.splitlines():
    if line.startswith("PULSES") or not line.strip():
        continue
    for tok in line.split(","):
        tok = tok.strip()
        if re.fullmatch(r"-?\d+", tok):
            nums.append(int(tok))

# split into bursts at 0 markers
bursts, cur = [], []
for v in nums:
    if v == 0:
        if cur:
            bursts.append(cur)
            cur = []
    else:
        cur.append(v)
if cur:
    bursts.append(cur)


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def bits_from_burst(burst, T, invert):
    """Expand pulses to a bit list. High=1 unless inverted."""
    bits = []
    for w in burst:
        lvl = 1 if w > 0 else 0
        if invert:
            lvl ^= 1
        n = max(1, int(round(abs(w) / T)))
        bits.extend([lvl] * n)
    return bits


def uart_decode(bits, msb_first=False):
    """Decode idle-high UART (LSB-first default). Returns bytes."""
    out = bytearray()
    i, n = 0, len(bits)
    # skip leading idle (1s)
    while i < n:
        # find start bit (0)
        while i < n and bits[i] == 1:
            i += 1
        if i >= n:
            break
        # i at start bit (0). data bits at i+1..i+8, stop at i+9
        if i + 9 >= n:
            break
        data = bits[i + 1:i + 9]
        byte = 0
        for k in range(8):
            bit = data[k]
            if msb_first:
                byte = (byte << 1) | bit
            else:
                byte |= bit << k
        out.append(byte)
        # advance past stop bit region; resync to next high->low
        i = i + 9
        # move to end of stop (skip 1s handled at loop top)
    return bytes(out)


def score(data):
    hits = []
    for i in range(0, len(data) - 7):
        if data[i + 1] in (0x03, 0x06):
            if crc16(data[i:i + 6]) == (data[i + 6] | (data[i + 7] << 8)):
                hits.append(data[i:i + 8])
    # also count how many bytes look like 0x01 (slave addr)
    return hits


print("bursts=%d total_pulses=%d" % (len(bursts), len(nums)))
best = None
T = 3.6
results = []
while T <= 9.2:
    for invert in (False, True):
        for msb in (False, True):
            allbytes = bytearray()
            for b in bursts:
                allbytes.extend(uart_decode(bits_from_burst(b, T, invert), msb))
            hits = score(allbytes)
            n01 = allbytes.count(0x01)
            results.append((len(hits), n01, round(T, 2), invert, msb, bytes(allbytes)))
    T += 0.1

results.sort(key=lambda r: (r[0], r[1]), reverse=True)
print("\nTop candidates (crc_hits, count01, T, invert, msb):")
for hits, n01, T, inv, msb, data in results[:8]:
    print("  hits=%d n01=%d T=%.1f inv=%s msb=%s  bytes=%s"
          % (hits, n01, T, inv, msb, data[:20].hex()))

top = results[0]
if top[0] > 0:
    print("\nDECODED MODBUS! T=%.1f (baud~%d) inv=%s msb=%s"
          % (top[2], int(1e6 / top[2]), top[3], top[4]))
    for h in score(top[5]):
        print("   frame:", h.hex())
else:
    # show best-by-n01 raw bytes for manual inspection
    print("\nNo CRC hit. Best-by-0x01-count decode for eyeballing:")
    best01 = max(results, key=lambda r: r[1])
    print("  T=%.1f inv=%s msb=%s" % (best01[2], best01[3], best01[4]))
    print("  bytes:", best01[5].hex())
