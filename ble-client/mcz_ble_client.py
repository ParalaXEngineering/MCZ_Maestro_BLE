#!/usr/bin/env python3
"""
MCZ Maestro+ BLE control client  (pure Python, laptop-side).

Speaks the stove PANEL's local BLE protocol directly from a computer — the same
protocol foyewmaddeeb/mcz-maestro-ble runs on an ESP32. Use it to talk to:
  * a real MCZ stove (advertises as "MCZ_EP"), or
  * a dev board flashed with the panel firmware dump (emulated panel — see FLASHING.md;
    note: with no mainboard on the panel's UART2, register READS won't be answered, but
    discovery / pairing / service 0xABF0 / frame acceptance all validate).

Protocol (custom GATT service 0xABF0):
  * write encrypted frames to characteristic 0xABF1 (write-no-response)
  * responses + status pushes arrive as Notify on 0xABF2
  * frame = AES-128-CBC(KEY1, IV0) over:
        [4B counter LE][16B TOKEN][Modbus-RTU PDU][PKCS#7 pad to 16]
  * inside: standard Modbus RTU, slave 0x01, func 0x03 read / 0x06 write, CRC16 poly 0xA001
  * the panel also pushes status on 0xABF2 framed "## [type][frag] ...", fragmented,
    AES-encrypted with the same key/token; its length is never a multiple of 16.
  KEY1/IV0/TOKEN are global for this firmware generation and were verified present in the dump.

Deps:  pip install bleak cryptography
Examples:
  python mcz_ble_client.py selftest                      # offline crypto round-trip (no hardware)
  python mcz_ble_client.py scan
  python mcz_ble_client.py monitor                        # connect, subscribe, poll status block
  python mcz_ble_client.py read  0x02BC 51
  python mcz_ble_client.py write 0x03F7 0x00D2            # setpoint 21.0C (210 = 0x00D2)
  python mcz_ble_client.py settemp 21.0
  python mcz_ble_client.py setpower 3
  python mcz_ble_client.py repl
"""
import argparse
import asyncio
import struct
import sys

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    sys.exit("pip install cryptography")

# ---- secrets (global for this firmware generation; verified in the dump) ----
KEY1  = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0   = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd345126" "39377b05a2510de725fc75")  # 16 bytes

assert len(KEY1) == 16 and len(IV0) == 16 and len(TOKEN) == 16

# ---- BLE UUIDs (16-bit -> full) ----
def uuid16(x): return f"0000{x:04x}-0000-1000-8000-00805f9b34fb"
SVC   = uuid16(0xABF0)
CH_TX = uuid16(0xABF1)   # write
CH_RX = uuid16(0xABF2)   # notify
TARGET_PREFIX = "MCZ_EP"

# ---- register map (from oven.h, verified against a real oven) ----
REG = {
    "setpoint": 0x03F7, "power": 0x03EB, "mode": 0x03E9, "onoff": 0x038A,
    "fan": 0x03FA, "silent": 0x03EC,
    "room": 0x02BC, "board": 0x02C1, "fumes": 0x02C5, "state": 0x0320,
    "phase": 0x0322, "mode_live": 0x032E, "flags": 0x0332, "fan_comb": 0x02CE,
    "fan_room": 0x02D1, "fan_live": 0x0324, "serial": 0x0ADC,
}
MODES = {0: "Manual", 1: "Auto", 2: "Overnight", 3: "Comfort?", 4: "Turbo?"}
STATES = {0x0000: "Off", 0x0101: "Cleaning", 0x0201: "Loading", 0x0301: "Start 1",
          0x0401: "Start 2", 0x0501: "Stabilization", 0x0601: "Anti-condensation",
          0x0202: "On", 0x0103: "Turning off"}
STATUS_BASE = 0x02BA


# ---- Modbus CRC16 (poly 0xA001), returned as (lo, hi) little-endian ----
def modbus_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def aes_encrypt(plain: bytes) -> bytes:
    c = Cipher(algorithms.AES(KEY1), modes.CBC(IV0))  # fixed IV, as the firmware does
    e = c.encryptor()
    return e.update(plain) + e.finalize()


def aes_decrypt(cipher: bytes) -> bytes:
    c = Cipher(algorithms.AES(KEY1), modes.CBC(IV0))
    d = c.decryptor()
    return d.update(cipher) + d.finalize()


def build_frame(pdu: bytes, counter: int) -> bytes:
    """[4B counter LE][16B token][pdu][crc16 LE][PKCS#7 pad] -> AES-CBC."""
    body = struct.pack("<I", counter & 0xFFFFFFFF) + TOKEN + pdu + modbus_crc(pdu)
    pad = 16 - (len(body) % 16)
    if pad == 0:
        pad = 16
    body += bytes([pad]) * pad
    return aes_encrypt(body)


def modbus_read_pdu(reg: int, count: int) -> bytes:
    return bytes([0x01, 0x03, reg >> 8, reg & 0xFF, count >> 8, count & 0xFF])


def modbus_write_pdu(reg: int, val: int) -> bytes:
    return bytes([0x01, 0x06, reg >> 8, reg & 0xFF, (val >> 8) & 0xFF, val & 0xFF])


def parse_frame(cipher: bytes):
    """Decrypt an AES-Modbus response frame. Returns (counter, modbus_pdu) or None."""
    if len(cipher) % 16 or len(cipher) < 32:
        return None
    pt = aes_decrypt(cipher)
    counter = struct.unpack_from("<I", pt, 0)[0]
    if pt[4:20] != TOKEN:
        return None, None
    # strip PKCS#7
    pad = pt[-1]
    end = len(pt) - pad if 1 <= pad <= 16 else len(pt)
    return counter, pt[20:end]


def decode_read_response(pdu: bytes, base_reg: int):
    """Modbus func 03 response: 01 03 <byteCount> <data..> <crc>. Yields (reg,val)."""
    if len(pdu) < 3 or pdu[1] != 0x03:
        return
    nbytes = pdu[2]
    data = pdu[3:3 + nbytes]
    for i in range(0, len(data) - 1, 2):
        yield base_reg + i // 2, (data[i] << 8) | data[i + 1]


# --------------------------------------------------------------------------- #
class MczBle:
    def __init__(self, address=None, name_prefix=TARGET_PREFIX):
        self.address = address
        self.name_prefix = name_prefix
        self.client = None
        self.counter = 0x6A418000
        self.tx = None
        self.regs = {}                 # reg -> value
        self._bc_buf = bytearray()     # ## reassembly
        self._bc_active = False
        self._last_read_base = 0x02BC

    async def _find(self, timeout):
        from bleak import BleakScanner
        print(f"[scan] looking for '{self.name_prefix}*' ({timeout}s)…")
        devs = await BleakScanner.discover(timeout=timeout, return_adv=True)
        for addr, (dev, adv) in devs.items():
            nm = adv.local_name or dev.name or ""
            mark = "MATCH" if self.name_prefix.lower() in nm.lower() else "     "
            print(f"  {mark} {addr}  {nm!r}  rssi={adv.rssi}")
            if mark == "MATCH":
                return addr
        return None

    async def connect(self, timeout=10.0, do_pair=False, require_service=True):
        from bleak import BleakClient
        if not self.address:
            self.address = await self._find(timeout)
            if not self.address:
                raise RuntimeError("No MCZ_EP found. Real stove: press +/- or power-cycle to "
                                   "enter pairing mode. Dev board: check serial for 'ADV start'.")
        from bleak.exc import BleakError
        last = None
        for attempt in range(1, 7):
            self.client = BleakClient(self.address, timeout=20.0,
                                      disconnected_callback=lambda c: print("[link] disconnected"))
            try:
                await self.client.connect()
                # some peripherals drop unencrypted discovery; pair immediately, then re-check
                if not list(self.client.services):
                    raise BleakError("no services after connect")
                break
            except Exception as e:
                last = e
                print(f"[connect] attempt {attempt} failed: {type(e).__name__}: {e}")
                try:
                    if self.client.is_connected:
                        await self.client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(1.5)
        else:
            raise RuntimeError(f"could not establish a stable connection: {last}")
        print(f"[connected] {self.address}  mtu={self.client.mtu_size}")
        if do_pair:
            try:
                await self.client.pair()      # Just Works; no-op/handled by OS on macOS
                print("[paired]")
            except Exception as e:
                print(f"[pair] skipped/failed: {e}")
        svc = self.client.services.get_service(SVC)
        if not svc:
            print("[!] service 0xABF0 not found via 16-bit UUID.")
            if require_service:
                await self.enumerate()
                raise RuntimeError("0xABF0 missing — see full GATT dump above")
            return
        self.tx = svc.get_characteristic(CH_TX)
        await self.client.start_notify(CH_RX, self._on_notify)
        print(f"[ready] tx={CH_TX} notify={CH_RX} subscribed")

    async def enumerate(self):
        """Full GATT walk: every service/characteristic/descriptor, read readables."""
        print("\n===== FULL GATT DATABASE (live) =====")
        notif = []
        for s in self.client.services:
            print(f"[service] {s.uuid}  {s.description}")
            for ch in s.characteristics:
                props = ",".join(ch.properties)
                print(f"    [char] {ch.uuid}  handle={ch.handle}  ({props})")
                if {"notify", "indicate"} & set(ch.properties):
                    notif.append(ch)
                if "read" in ch.properties:
                    try:
                        v = await self.client.read_gatt_char(ch)
                        print(f"        read = {bytes(v).hex()}  {bytes(v)!r}")
                    except Exception as e:
                        print(f"        read failed: {e}")
                for d in ch.descriptors:
                    print(f"        [desc] {d.uuid} handle={d.handle}")
        print("=====================================\n")
        return notif

    async def disconnect(self):
        if self.client and self.client.is_connected:
            try:
                await self.client.stop_notify(CH_RX)
            except Exception:
                pass
            await self.client.disconnect()

    def _on_notify(self, _char, data: bytearray):
        data = bytes(data)
        # 1) "##" status broadcast (fragmented, len % 16 != 0)
        if len(data) >= 4 and data[0] == 0x23 and data[1] == 0x23 and (len(data) % 16):
            frag = data[3]
            if frag == 0x01:
                self._bc_buf = bytearray(); self._bc_active = True
            elif frag != 0x02:
                print(f"[##] type={data[2]:02x} frag={frag:02x} (ignored)")
                return
            if not self._bc_active:
                return
            self._bc_buf += data[4:]
            if frag != 0x02:
                return                       # wait for final fragment
            self._bc_active = False
            if len(self._bc_buf) % 16:
                print(f"[##] reassembled {len(self._bc_buf)}B (not /16)"); return
            pt = aes_decrypt(bytes(self._bc_buf))
            if pt[4:20] != TOKEN:
                print("[##] token mismatch"); return
            pad = pt[-1]; end = len(pt) - pad if 1 <= pad <= 16 else len(pt)
            payload = pt[20:end]
            for i in range(0, len(payload) - 1, 2):
                self._store(STATUS_BASE + i // 2, (payload[i] << 8) | payload[i + 1])
            print(f"[##] status broadcast: {len(payload)//2} regs  {self.summary()}")
            return
        # 2) AES-Modbus response frame
        res = parse_frame(data)
        if not res or res[0] is None:
            print(f"[rx] raw {len(data)}B: {data.hex()} (short/MTU? token mismatch?)")
            return
        counter, pdu = res
        if pdu and pdu[1] == 0x03:
            for reg, val in decode_read_response(pdu, self._last_read_base):
                self._store(reg, val)
            print(f"[rx] read reply ctr={counter:08x} -> {self.summary()}")
        elif pdu and pdu[1] == 0x06:
            reg = (pdu[2] << 8) | pdu[3]; val = (pdu[4] << 8) | pdu[5]
            print(f"[rx] write ack reg=0x{reg:04X} val=0x{val:04X}")
        else:
            print(f"[rx] pdu {pdu.hex() if pdu else None}")

    def _store(self, reg, val):
        self.regs[reg] = val
        if reg == REG["serial"]:
            pass  # 0x0ADC block is ASCII across several regs; left raw here

    async def _send(self, pdu: bytes):
        frame = build_frame(pdu, self.counter); self.counter += 1
        await self.client.write_gatt_char(self.tx, frame, response=False)

    async def read(self, reg, count):
        self._last_read_base = reg
        print(f"--> READ  0x{reg:04X} x{count}")
        await self._send(modbus_read_pdu(reg, count))

    async def write(self, reg, val):
        print(f"--> WRITE 0x{reg:04X} = 0x{val:04X} ({val})   ** changes the oven **")
        await self._send(modbus_write_pdu(reg, val))

    # convenience
    async def poll(self):        await self.read(0x02BC, 0x33)
    async def settemp(self, c):  await self.write(REG["setpoint"], int(round(c * 10)))
    async def setpower(self, p): await self.write(REG["power"], max(1, min(5, p)))
    async def setmode(self, m):  await self.write(REG["mode"], m)
    async def setfan(self, l):   await self.write(REG["fan"], 6 if l == 0 else max(1, min(5, l)))
    async def onoff_toggle(self):await self.write(REG["onoff"], 1)

    def summary(self):
        g = self.regs
        def t(r): return f"{g[r]/10:.1f}C" if r in g else "?"
        ph = g.get(REG["phase"]); st = g.get(REG["state"])
        return (f"room={t(REG['room'])} set={t(REG['setpoint'])} "
                f"pow={g.get(REG['power'],'?')} phase={'On' if ph==3 else 'Off' if ph==1 else ph} "
                f"state={STATES.get(st, hex(st) if st is not None else '?')}")


# --------------------------------------------------------------------------- #
def selftest():
    """Validate the crypto/framing offline (no hardware)."""
    print("== selftest: build a setpoint=21.0C write frame, then decrypt it back ==")
    pdu = modbus_write_pdu(REG["setpoint"], 210)
    print("modbus pdu     :", pdu.hex(), " (01 06 03f7 00d2)")
    print("crc16          :", modbus_crc(pdu).hex())
    frame = build_frame(pdu, 0x6A418000)
    print(f"encrypted frame: {frame.hex()}  ({len(frame)}B, /16={len(frame)%16==0})")
    ctr, back = parse_frame(frame)
    assert back is not None, "token check failed"
    print(f"decrypted ctr  : {ctr:08x}")
    print(f"decrypted pdu  : {back.hex()}")
    assert back[:6] == pdu, "round-trip mismatch"
    assert modbus_crc(back[:6]) == back[6:8], "crc mismatch"
    print("OK — crypto, token, CRC and PKCS#7 all round-trip. Client is protocol-correct.")


async def run(args):
    if args.cmd == "selftest":
        selftest(); return
    m = MczBle(address=args.address, name_prefix=args.name)
    if args.cmd == "scan":
        await m._find(args.timeout); return
    if args.cmd == "dump":
        # full survey: enumerate everything, subscribe to all notifiers, poke it, listen.
        await m.connect(timeout=args.timeout, do_pair=args.pair, require_service=False)
        notif = await m.enumerate()
        for ch in notif:
            try:
                await m.client.start_notify(ch, m._on_notify)
                print(f"[subscribed] {ch.uuid}")
            except Exception as e:
                print(f"[subscribe failed] {ch.uuid}: {e}")
        # if the standard write char exists, send a poll + a couple of reads to provoke replies
        svc = m.client.services.get_service(SVC)
        if svc and svc.get_characteristic(CH_TX):
            m.tx = svc.get_characteristic(CH_TX)
            print("[poke] sending poll(0x02BC) + read(0x0320,4) + read(0x0ADC,8)")
            try:
                await m.poll(); await asyncio.sleep(1.0)
                await m.read(0x0320, 4); await asyncio.sleep(1.0)
                await m.read(0x0ADC, 8)
            except Exception as e:
                print(f"[poke] write failed: {e}")
        print(f"[listen] {args.timeout}s for notifications / ## broadcasts …")
        await asyncio.sleep(args.timeout)
        await m.disconnect()
        return
    await m.connect(timeout=args.timeout, do_pair=args.pair)
    try:
        if args.cmd == "monitor":
            await m.poll()
            await asyncio.sleep(args.timeout)
        elif args.cmd == "read":
            await m.read(int(args.a, 0), int(args.b, 0)); await asyncio.sleep(4)
        elif args.cmd == "write":
            await m.write(int(args.a, 0), int(args.b, 0)); await asyncio.sleep(3)
        elif args.cmd == "settemp":
            await m.settemp(float(args.a)); await asyncio.sleep(3)
        elif args.cmd == "setpower":
            await m.setpower(int(args.a)); await asyncio.sleep(3)
        elif args.cmd == "repl":
            print("commands: poll | read <reg> <cnt> | write <reg> <val> | settemp <c> | "
                  "setpower <1-5> | setfan <0-5> | toggle | quit")
            loop = asyncio.get_event_loop()
            while True:
                line = (await loop.run_in_executor(None, input, "MCZ> ")).split()
                if not line: continue
                c = line[0].lower()
                if c in ("quit", "exit"): break
                try:
                    if c == "poll": await m.poll()
                    elif c == "read": await m.read(int(line[1],0), int(line[2],0))
                    elif c == "write": await m.write(int(line[1],0), int(line[2],0))
                    elif c == "settemp": await m.settemp(float(line[1]))
                    elif c == "setpower": await m.setpower(int(line[1]))
                    elif c == "setfan": await m.setfan(int(line[1]))
                    elif c == "toggle": await m.onoff_toggle()
                    else: print("?")
                except Exception as e:
                    print("err:", e)
                await asyncio.sleep(1.0)
    finally:
        await m.disconnect()


def main():
    ap = argparse.ArgumentParser(description="MCZ Maestro+ BLE control client")
    ap.add_argument("cmd", choices=["selftest","scan","dump","monitor","read","write",
                                    "settemp","setpower","repl"])
    ap.add_argument("a", nargs="?"); ap.add_argument("b", nargs="?")
    ap.add_argument("--address"); ap.add_argument("--name", default=TARGET_PREFIX)
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--pair", action="store_true", help="explicitly pair (Linux/BlueZ)")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
