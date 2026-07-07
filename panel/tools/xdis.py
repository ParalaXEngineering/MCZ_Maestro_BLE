#!/usr/bin/env python3
"""Robust-ish Xtensa (ESP32 LX6) disassembly helper over the panel flash image.

Capstone's Xtensa backend desyncs on this image (emits ESP32-S3 'ee.*' vector
ops that cannot occur on an LX6, then loses alignment). This wrapper:
  * knows Xtensa instruction length from the first byte (density option), so it
    can step deterministically without trusting capstone's stream,
  * uses capstone only to *render* each individually-sized instruction,
  * flags 'ee.*'/vector garbage as a desync marker,
  * can brute-force the start offset so a target address lands on a boundary.

Usage:
  xdis.py dis   <start_hex> <end_hex>
  xdis.py at    <target_hex> [back=0x40] [fwd=0x40]     # brute-force alignment to hit target
  xdis.py bytes <start_hex> <n>                          # raw hex dump
  xdis.py xref  <target_hex>                             # l32r references (reliable)
"""
import struct, sys, os
import capstone

# Resolve the firmware image path: sibling ../firmware/ (when run from panel/tools/),
# or panel/firmware/ under the current working directory (when run from the repo root).
_here = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.path.join(_here, "..", "firmware", "used_flash_0x0.bin"),
    os.path.join(os.getcwd(), "panel", "firmware", "used_flash_0x0.bin"),
]
IMGPATH = next((p for p in CANDIDATES if os.path.exists(p)), CANDIDATES[0])
d = open(IMGPATH, "rb").read()

SEGS = [(0x3f400020, 0x1992a4, 0x10020),
        (0x400d0020, 0x11202c, 0x1b0020),
        (0x40080000, 0x1fad8, 0x2c3f4c)]

def v2f(v):
    for lv, ln, fo in SEGS:
        if lv <= v < lv + ln:
            return fo + (v - lv)
    return None

def word(v):
    fo = v2f(v)
    return struct.unpack('<I', d[fo:fo+4])[0] if fo is not None else None

def rdstr(v):
    fo = v2f(v)
    if fo is None:
        return None
    try:
        e = d.index(b'\x00', fo)
        s = d[fo:e]
        if 1 <= len(s) <= 60 and all(32 <= c < 127 for c in s):
            return s.decode()
    except Exception:
        pass
    return None

def ilen(b0):
    """Xtensa instruction length in bytes from the first byte.
    Density (16-bit) instrs: op0 (bits3:0) in {0x8 L32I.N,0x9 S32I.N,0xC,0xD}.
    Everything else is 24-bit (3 bytes). op0=0xF has a couple 16-bit subforms
    but on ESP32 code the common ones we hit are 3-byte; we special-case none."""
    op0 = b0 & 0x0f
    if op0 in (0x8, 0x9, 0xC, 0xD):
        return 2
    return 3

md = capstone.Cs(capstone.CS_ARCH_XTENSA, capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = False

def ann(mnem, opstr):
    if 'l32r' not in mnem:
        return ''
    import re
    m = re.search(r'0x[0-9a-f]+', opstr)
    if not m:
        return ''
    lit = int(m.group(0), 16)
    val = word(lit)
    if val is None:
        return ''
    s = rdstr(val)
    return '  ; ->%r' % s if s is not None else '  ; =0x%08x' % val

def render_one(addr):
    """Render exactly one instruction at addr using our length; return (text, length)."""
    fo = v2f(addr)
    if fo is None:
        return ('(no map)', 1)
    b0 = d[fo]
    L = ilen(b0)
    chunk = d[fo:fo+L]
    try:
        ins = next(md.disasm(chunk, addr))
        mnem, opstr = ins.mnemonic, ins.op_str
        # If capstone consumed a different length, trust our L for stepping but note it.
        text = '%-11s %s%s' % (mnem, opstr, ann(mnem, opstr))
    except StopIteration:
        text = '.byte ' + ' '.join('%02x' % c for c in chunk)
    vector = any(t in text for t in ('ee.', 'q0', 'q1', 'q2', 'q3', 'q4', 'q5', 'q6', 'q7', 'f0,', 'wur', 'rur'))
    return (text, L, vector, chunk)

def dis(start, end):
    a = start
    out = []
    while a < end:
        text, L, vector, chunk = render_one(a)
        flag = '  <== DESYNC?' if vector else ''
        out.append('0x%08x  %s  [%s]%s' % (a, text, ' '.join('%02x' % c for c in chunk), flag))
        a += L
    return out

def score(lines):
    return sum(1 for ln in lines if 'DESYNC' in ln or '.byte' in ln)

def at(target, back, fwd):
    best = None
    for delta in range(0, 24):
        base = target - back - delta
        if v2f(base) is None:
            continue
        # walk from base; check we land exactly on target
        a = base
        boundaries = set()
        while a < target + fwd:
            boundaries.add(a)
            fo = v2f(a)
            if fo is None:
                break
            a += ilen(d[fo])
        if target in boundaries:
            lines = dis(base, target + fwd)
            s = score(lines)
            if best is None or s < best[0]:
                best = (s, base, lines)
    if best is None:
        return ['(could not align to target)']
    return ['(aligned base 0x%08x, desync_score=%d)' % (best[1], best[0])] + best[2]

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'dis':
        print('\n'.join(dis(int(sys.argv[2], 16), int(sys.argv[3], 16))))
    elif cmd == 'at':
        t = int(sys.argv[2], 16)
        back = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x40
        fwd = int(sys.argv[4], 16) if len(sys.argv) > 4 else 0x40
        print('\n'.join(at(t, back, fwd)))
    elif cmd == 'bytes':
        v = int(sys.argv[2], 16)
        n = int(sys.argv[3], 16) if len(sys.argv) > 3 else 32
        fo = v2f(v)
        print(' '.join('%02x' % c for c in d[fo:fo+n]))
    elif cmd == 'xref':
        tv = int(sys.argv[2], 16)
        hits = []
        for lv, ln, fo in [(0x400d0020, 0x11202c, 0x1b0020), (0x40080000, 0x1fad8, 0x2c3f4c)]:
            A = lv
            while A < lv + ln - 2:
                b0 = d[fo + (A - lv)]
                if (b0 & 0x0f) == 0x01:  # l32r
                    imm = d[fo + (A - lv) + 1] | (d[fo + (A - lv) + 2] << 8)
                    lit = ((A + 3) & ~3) + (imm - 0x10000) * 4
                    if word(lit) == tv:
                        hits.append(A)
                A += 1
        print('xrefs to 0x%08x:' % tv, [hex(x) for x in hits])
