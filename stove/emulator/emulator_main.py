# MCZ mainboard emulator v2 - AES-wrapped Modbus slave for the Maestro+ panel.
#
# The panel<->mainboard UART2 link (115200 8N1, panel TX on our GPIO5) carries the
# SAME crypto as BLE: AES-128-CBC(KEY1, IV0) over
#     [4B counter LE][16B TOKEN][Modbus PDU][CRC16-modbus][PKCS#7 pad to 16].
# The panel polls with vendor func 0x41 (read) and func 0x10 (write-multiple),
# ~1/s. We decrypt, answer, and re-encrypt so the panel sees a live mainboard and
# stops its endless UART timeout loop.
#
# NOTE (resolved 2026-07-07): this reply does NOT open the panel's BLE control gate,
# and no reply can. That gate is a commissioning/pairing gate, not a mainboard-health
# check, and reads no mainboard register to decide it - see
# ../../docs/ble-readiness-gate-RESOLVED.md. The panel already ACCEPTS this reply with
# no parser error; that is all the emulator needs to do. To open BLE control, put the
# panel through pairing/provisioning (that sets the enable bit), not a better reply.
# Verify this reply's framing offline with diagnostics/verify_reply.py.
#
# The panel narrates failures on ITS console (No x16 / CRC Err / OtherAddress /
# Function Error / Incomplete Message / Exeption) - watch COM39 if you refine the
# register layout against a real mainboard for accurate BLE reads later.
from machine import UART
import time
try:
    from cryptolib import aes
except ImportError:
    from ucryptolib import aes

KEY1 = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0 = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd34512639377b05a2510de725fc75")


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc


def decrypt(ct):
    return aes(KEY1, 2, IV0).decrypt(ct)


def encrypt(pt):
    return aes(KEY1, 2, IV0).encrypt(pt)


def wrap(counter, pdu):
    """Build an encrypted frame: [ctr][token][pdu][crc][pkcs7 pad to 16]."""
    body = counter.to_bytes(4, "little") + TOKEN + pdu
    c = crc16(pdu)
    body += bytes((c & 0xFF, (c >> 8) & 0xFF))
    pad = 16 - (len(body) % 16)          # PKCS#7 (full block if already aligned)
    body += bytes((pad,)) * pad
    return encrypt(body)


def build_response(pdu):
    """Return response PDU (without CRC/crypto) for a request PDU, or None."""
    addr, func = pdu[0], pdu[1]
    if func == 0x41:                     # vendor read starting at 'reg', 'cnt' regs
        reg = (pdu[2] << 8) | pdu[3]
        cnt = (pdu[4] << 8) | pdu[5]
        n = min(cnt, 20)                 # short frame: panel only accepts small replies
        # plausible "mainboard present, stove ON/ready" status image
        regmap = {
            0x02BC: 210, 0x02C1: 250, 0x02C5: 450, 0x02C9: 1,
            0x02CE: 1500, 0x02D1: 1200,
            0x0320: 0x0202, 0x0322: 3, 0x0324: 3, 0x032E: 1, 0x0332: 0,
            0x0334: 5, 0x0340: 1000,
        }
        data = bytearray()
        for i in range(n):
            v = regmap.get(reg + i, 0)
            data.append((v >> 8) & 0xFF)
            data.append(v & 0xFF)
        return bytes((addr, 0x41)) + bytes(data)
    if func == 0x10:                     # write-multiple: echo addr func reg qty
        return pdu[0:6]
    if func == 0x03:                     # standard read, just in case
        cnt = (pdu[4] << 8) | pdu[5]
        return bytes((addr, 0x03, cnt * 2)) + bytes(cnt * 2)
    return None


def main():
    # Large txbuf so a multi-block response is handed to the driver in one shot
    # and transmitted contiguously (no inter-byte gaps that fragment the frame).
    uart = UART(2, baudrate=115200, bits=8, parity=None, stop=1, tx=4, rx=5,
                timeout=0, rxbuf=4096, txbuf=2048)
    print("EMU v2 up: UART2 115200 8N1 tx=4 rx=5, AES/token ready")
    cur = bytearray()
    last = time.ticks_ms()
    n_ok = n_resp = 0
    hb = time.ticks_ms()

    while True:
        n = uart.any()
        now = time.ticks_ms()
        if n:
            cur.extend(uart.read(n))
            last = now
        elif cur and time.ticks_diff(now, last) > 15:
            frame = bytes(cur)
            cur = bytearray()
            if len(frame) >= 32 and len(frame) % 16 == 0:
                pt = decrypt(frame)
                if pt[4:20] == TOKEN:
                    n_ok += 1
                    counter = int.from_bytes(pt[0:4], "little")
                    body = pt[20:]
                    pad = body[-1]
                    if 1 <= pad <= 16:
                        body = body[:-pad]
                    pdu, rxcrc = body[:-2], body[-2] | (body[-1] << 8)
                    if crc16(pdu) == rxcrc and len(pdu) >= 2:
                        resp_pdu = build_response(pdu)
                        if resp_pdu is not None:
                            uart.write(wrap(counter, resp_pdu))
                            n_resp += 1
                            print("REQ ctr=%d func=0x%02x reg=0x%04x len=%d -> RESP pdu=%dB"
                                  % (counter, pdu[1], (pdu[2] << 8) | pdu[3],
                                     len(pdu), len(resp_pdu)))
                        else:
                            print("REQ func=0x%02x (no responder) pdu=%s"
                                  % (pdu[1], pdu.hex()))
                    else:
                        print("bad inner crc pdu=%s" % pdu.hex())
                else:
                    print("token mismatch len=%d" % len(frame))

        if time.ticks_diff(time.ticks_ms(), hb) > 4000:
            print("hb decoded_ok=%d responded=%d" % (n_ok, n_resp))
            hb = time.ticks_ms()


main()
