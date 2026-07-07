# The local BLE control protocol

**This is the document that matters for a Home Assistant integration.** It fully specifies the
panel's local control channel: the GATT service, the AES message envelope, the frame layout, the
register map, and pairing. Everything a client needs to read status and send commands over BLE — the
same thing the MCZ phone app does at close range — is here.

The reference implementation of all of it is
[`ble-client/mcz_ble_client.py`](../ble-client/mcz_ble_client.py); `python mcz_ble_client.py selftest`
builds, encrypts, decrypts and verifies a real command frame with no hardware.

---

## GATT layout

The panel advertises as `MCZ_EP<serial>` (e.g. `MCZ_EP000000` when NVS is wiped) and exposes:

| UUID | Role |
|------|------|
| `0xABF0` | primary service |
| `0xABF1` | write-no-response — commands **in** |
| `0xABF2` | notify — responses and status pushes **out** |

Negotiate **MTU 517**.

## How control works

1. Scan for `MCZ_EP*`, connect, negotiate MTU 517, subscribe to notifications on `0xABF2`.
2. **Read:** send an AES-wrapped `0x03` read PDU to `0xABF1`; the reply arrives on `0xABF2`.
3. **Write:** send an AES-wrapped `0x06` write PDU to `0xABF1`.
4. The panel also pushes unsolicited status on `0xABF2`, framed with `##` (see
   [Status broadcasts](#status-broadcasts)).

---

## The message envelope

Both local links (BLE and the internal UART2 link) wrap their Modbus payloads in the **same**
AES-128-CBC envelope.

| Item | Value |
|------|-------|
| Algorithm / mode | AES-128-CBC |
| Key / block size | 16 bytes |
| Padding | PKCS#7 to a 16-byte multiple |
| IV | **fixed** (`IV0`) for every message — never chained |

**The fixed IV is the interop gotcha.** CBC normally uses a fresh random IV per message; this
firmware re-copies the same constant `IV0` before every encrypt/decrypt, so there is no chaining
between messages. Replicate this exactly: use `IV0` as the IV every time, never the previous
ciphertext block.

### Static values (compiled into the firmware)

These are constants baked into the firmware image, **shared across this firmware generation** — not
per-device secrets, and already published by the community project linked from the root README.
Per-device identity is only the BLE MAC and the stove serial number (register `0x0ADC`).

| Name | Hex (16 bytes) | Role |
|------|----------------|------|
| `KEY1` | `6e296b0bbb1d43f36e47f72e7b6f2e77` | AES-128 key |
| `IV0`  | `da1a557349f25c641b1a368af5b218a7` | fixed CBC IV |
| `TOKEN`| `31dd34512639377b05a2510de725fc75` | plaintext marker the receiver checks |

(Located in the flash dump at offsets `0x6ce96` / `0x1041c` / `0x6ce86` — see
[reference/firmware-disassembly.md](reference/firmware-disassembly.md).)

### Reference implementation (Python)

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY1  = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0   = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd34512639377b05a2510de725fc75")

def decrypt(ct: bytes) -> bytes:               # fresh IV0 every call
    d = Cipher(algorithms.AES(KEY1), modes.CBC(IV0)).decryptor()
    return d.update(ct) + d.finalize()

def encrypt(pt: bytes) -> bytes:               # pt must be a 16-byte multiple
    e = Cipher(algorithms.AES(KEY1), modes.CBC(IV0)).encryptor()
    return e.update(pt) + e.finalize()
```

On the MicroPython emulator the same is available via `cryptolib`: `aes(KEY1, 2, IV0)` (mode 2 = CBC),
a fresh object per message.

---

## Frame format

The plaintext, before encryption:

```
offset  size  field
------  ----  ------------------------------------------------------------
  0      4    counter        little-endian, increments once per message
  4     16    TOKEN          constant 31dd34512639377b05a2510de725fc75
 20      N    Modbus PDU     the request or response (see below)
20+N     2    CRC-16         Modbus CRC of the PDU only, low byte first
22+N     P    PKCS#7 pad     P = 16 - ((22+N) mod 16), each byte = P
```

The whole thing (`22 + N + P` bytes, always a multiple of 16) is AES-128-CBC encrypted with `KEY1`
and `IV0`. On the wire you only ever see ciphertext.

- **counter** — 32-bit LE, +1 per message. The receiver doesn't require a specific value, only that
  it's present.
- **TOKEN** — after decrypting, the receiver checks these 16 bytes; a mismatch means "not for me /
  wrong key" and the message is dropped.
- **CRC-16** — standard Modbus CRC (poly `0xA001`), over the **PDU only**, appended little-endian.
- **PKCS#7** — if already a 16-byte multiple, a full extra block of `0x10` bytes is added (standard).

### The Modbus PDU

Standard Modbus RTU, slave address `0x01`. Function codes differ by link:

| Link | Read | Write |
|------|------|-------|
| **BLE control (`0xABF0`)** | `0x03` (read holding registers) | `0x06` (write single register) |
| UART2 mainboard link | `0x41` (vendor read) | `0x10` (write multiple) |

Request PDU shapes:

```
0x03 read  : 01 03 REGhi REGlo CNThi CNTlo
0x06 write : 01 06 REGhi REGlo VALhi VALlo
```

### CRC-16 (Modbus)

```python
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc
# append as: bytes([crc & 0xFF, (crc >> 8) & 0xFF])   # low byte first
```

### Worked example (a captured read request)

Ciphertext (32 bytes): `7662d40de8c5654a1c21a859a629ca4523be10fbbdc29dd7da153c39176fcc66`

Decrypts to:

```
be130000 | 31dd34512639377b05a2510de725fc75 | 014102bc012c | fdd4 | 04040404
 counter  |             TOKEN                |     PDU      | CRC  | PKCS#7(4)
```

Meaning: read register `0x02BC`, count `0x012C`. (This one is a `0x41` UART2 read; a BLE read is
identical but with function `0x03`.)

---

## Register map

Stove state and commands are Modbus registers on the mainboard, reached through the panel. Verified
against a real oven by the community project and cross-checked against this firmware; values marked
*assumed* still need confirmation on hardware.

### Writes (commands) — BLE function `0x06`

| Register | Meaning | Value |
|----------|---------|-------|
| `0x03F7` | Setpoint temperature | °C × 10 (e.g. `210` = 21.0 °C) |
| `0x03EB` | Power level | 1..5 |
| `0x03E9` | Mode | 0 = Manual, 1 = Auto, 2 = Overnight, 3 = Comfort\*, 4 = Turbo\* |
| `0x038A` | On/off | write `1` = press power button (a **toggle**) |
| `0x03FA` | Fan | 1..5 fixed, 6 = auto |
| `0x03EC` | Silent mode | 1 = on, 0 = off |

\* Modes 3/4 are assumed; verify against a real stove.

### Reads (status) — BLE function `0x03`

The app polls the main block as **read `0x02BC`, count `0x33`** (51 registers).

| Register | Meaning |
|----------|---------|
| `0x02BC` | Room temperature ÷10 |
| `0x02C1` | Board temperature ÷10 |
| `0x02C5` | Flue (fumes) temperature ÷10 |
| `0x02C9` | "Active" flag |
| `0x02CE` | Combustion fan RPM |
| `0x02D1` | Flue fan RPM |
| `0x0320` | Fine state code (table below) |
| `0x0322` | Coarse phase: 1 = Off, 3 = On |
| `0x0324` | Live fan level |
| `0x032E` | Live mode mirror |
| `0x0332` | Flags (bit6 = Chrono, bit5 = Silent) |
| `0x0334` | Ignition count |
| `0x0336`–`0x033F` | Time in power 1..5 (five 32-bit second counters) |
| `0x0340`/`0x0341` | Total worktime (32-bit seconds) |
| `0x0ADC` | Serial number (ASCII, spans several registers) |

### Fine-state codes (`0x0320`)

| Code | State | Code | State |
|------|-------|------|-------|
| `0x0000` | Off | `0x0501` | Stabilization |
| `0x0101` | Cleaning | `0x0601` | Anti-condensation |
| `0x0201` | Loading | `0x0202` | On |
| `0x0301` | Start 1 | `0x0103` | Turning off |
| `0x0401` | Start 2 | | |

### Why a full HA integration is hybrid

The MCZ app first fetches a **model profile** from the cloud (which registers/features exist for a
given model) and caches it, then controls over BLE. Raw register read/write doesn't need the profile
— it only decides which registers are meaningful for a model. So a complete integration is expected
to be hybrid: cloud (or a shipped table) for the profile, BLE for control. See
[integration.md](integration.md).

---

## Pairing and the readiness gate

- **BLE bonding is required:** Just Works (IO capability NoInputNoOutput), LE Secure Connections,
  bond = yes, MITM = no. The reference client calls `setSecurityAuth(true, false, true)` before
  connecting; on Linux/BlueZ pass `--pair`.
- **Commissioning:** a stove already bonded to a phone advertises *directed* to that phone only. To
  pair a new device, put the panel in pairing mode — press **+ and −** together — or clear the stored
  bond (on the bench, wipe NVS; see [setup.md](setup.md)).
- **The readiness gate:** the panel guards the control session behind two status bits in its connect
  handler (`[+0x54]` bit1 enable SET, `[+0x52]` bit2 fault CLEAR). The enable bit is set by the
  **commissioning/pairing flow**, *not* by mainboard communication. After the gate, an **empty
  whitelist auto-registers and accepts the first client** — this is how the app and community clients
  get in on first pairing. So on a real stove, entering pairing mode is the single action that opens
  the gate and gets the first client accepted. Full byte-level analysis:
  [reference/readiness-gate.md](reference/readiness-gate.md).

## Status broadcasts

Besides answering reads, the panel pushes unsolicited status on `0xABF2`. These are framed
differently: they start with `## ` (`0x23 0x23 [type] [frag]`), are **fragmented** (fragment `0x01`
first, `0x02` last), and are AES-encrypted with the same key/token. Quick discriminator: a `##`
payload length is **never** a multiple of 16, whereas an AES-Modbus frame always is. After reassembly
+ decrypt + token check, the payload is a register image beginning at `0x02BA` (`STATUS_BASE`).
