#!/usr/bin/env python3
"""Patch the bench panel app image to bypass the BLE readiness gate.

WHY: the panel's BLE connect handler (0x400d26ae) refuses control sessions until an
internal "enable" bit is set by the commissioning/pairing flow (see
docs/reference/readiness-gate.md). On a bare bench dev board that flow never runs, so
every connect is `rejected Nm0`. This makes the WHOLE BLE control stack (keys, framing,
0xABF0 reads/writes, pairing) untestable on the bench.

WHAT: this replaces one instruction at the top of the gate so control jumps straight past
BOTH gate checks into the whitelist logic (empty whitelist -> auto-register + accept):

    0x400d26bd  l8ui a8,[state+0x54]   (82 02 54)   ->   j 0x400d26cf   (86 03 00)

Then it recomputes the esp-image checksum byte and the appended SHA-256 so the 2nd-stage
bootloader still accepts the image.

SCOPE: bench validation only, on a spare ESP32 dev board. It does NOT reveal how a real,
unmodified panel opens the gate (that's commissioning/pairing; RESOLVED doc). It only lets
you prove the BLE control implementation end-to-end.

USAGE:
    python panel/tools/patch_open_gate.py \
        panel/firmware/flash_4mb/app_ota0.bin \
        panel/firmware/flash_4mb/app_ota0_gateopen.bin
Then flash the output to 0x10000 (the ota_0 app partition). See flash_4mb/README.md.
"""
import sys, struct, hashlib

# Gate instruction site, inside seg3 (IROM, load 0x400d0020, file data @0x1a0020).
GATE_VADDR = 0x400d26bd
ORIG = bytes.fromhex("820254")      # l8ui a8, a2, 0x54   (start of the two-gate check)
# j 0x400d26cf : Xtensa J, target = PC+4+imm18; imm18 = 0x400d26cf-0x400d26bd-4 = 0xE
#   word = (0xE << 6) | 0x06 = 0x386  -> little-endian bytes 86 03 00
PATCH = bytes.fromhex("860300")     # j 0x400d26cf  (skips BOTH gate checks)


def parse_image(d):
    """Return (num_seg, seg_list[(load,off,len)], checksum_pos, sha_pos, hash_appended)."""
    assert d[0] == 0xE9, "not an esp-image (magic != 0xE9)"
    nseg = d[1]
    hash_appended = d[23]
    p = 24
    segs = []
    for _ in range(nseg):
        load, ln = struct.unpack('<II', d[p:p+8])
        p += 8
        segs.append((load, p, ln))
        p += ln
    pad = 16 - (p % 16)
    cks_pos = p + pad - 1
    sha_pos = cks_pos + 1
    return nseg, segs, cks_pos, sha_pos, hash_appended


def recompute(d):
    """Recompute checksum byte and appended SHA-256 in-place (d is a bytearray)."""
    nseg, segs, cks_pos, sha_pos, hash_appended = parse_image(d)
    xor = 0xEF
    for _, off, ln in segs:
        for b in d[off:off+ln]:
            xor ^= b
    d[cks_pos] = xor & 0xFF
    if hash_appended:
        d[sha_pos:sha_pos+32] = hashlib.sha256(bytes(d[:sha_pos])).digest()
    return cks_pos, sha_pos, hash_appended


def vaddr_to_fileoff(segs, vaddr):
    for load, off, ln in segs:
        if load <= vaddr < load + ln:
            return off + (vaddr - load)
    raise ValueError("vaddr 0x%08x not in any segment" % vaddr)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    d = bytearray(open(src, "rb").read())
    _, segs, cks_pos, sha_pos, hash_appended = parse_image(d)
    fo = vaddr_to_fileoff(segs, GATE_VADDR)
    print("gate @ vaddr 0x%08x = file 0x%x : %s" % (GATE_VADDR, fo, d[fo:fo+9].hex()))
    if bytes(d[fo:fo+3]) != ORIG:
        print("REFUSING: bytes at gate are %s, expected %s (wrong image?)"
              % (d[fo:fo+3].hex(), ORIG.hex()))
        sys.exit(2)
    d[fo:fo+3] = PATCH
    print("patched to: %s   (l8ui ... -> j 0x400d26cf, bypasses both gates)" % d[fo:fo+9].hex())
    cks_pos, sha_pos, hash_appended = recompute(d)
    print("recomputed checksum @0x%x = 0x%02x ; sha256 @0x%x (hash_appended=%d)"
          % (cks_pos, d[cks_pos], sha_pos, hash_appended))
    open(dst, "wb").write(d)
    # self-verify
    d2 = bytearray(open(dst, "rb").read())
    _, segs2, cks2, sha2, ha2 = parse_image(d2)
    xor = 0xEF
    for _, off, ln in segs2:
        for b in d2[off:off+ln]:
            xor ^= b
    ok_cks = (d2[cks2] == (xor & 0xFF))
    ok_sha = (not ha2) or (d2[sha2:sha2+32] == hashlib.sha256(bytes(d2[:sha2])).digest())
    print("wrote %s (%d bytes). verify: checksum=%s sha256=%s"
          % (dst, len(d2), "OK" if ok_cks else "BAD", "OK" if ok_sha else "BAD"))
    if not (ok_cks and ok_sha):
        sys.exit(3)


if __name__ == "__main__":
    main()
