# Message encryption (AES-128-CBC)

Both local links (BLE control and the UART2 mainboard link) wrap their Modbus payloads in the same
symmetric envelope. This document covers the cipher and its parameters; the byte layout of the
plaintext is in [frame-format.md](frame-format.md).

## Parameters

| Item | Value |
|------|-------|
| Algorithm | AES-128 |
| Mode | CBC |
| Key length | 128 bit (16 bytes) |
| Block size | 16 bytes |
| Padding | PKCS#7 to a 16-byte multiple |
| IV | **Fixed** for every message (see below) |

### The fixed IV

CBC normally uses a fresh, random IV per message. This firmware does **not** — it re-copies the
same constant IV (`IV0`) before every encrypt/decrypt, so there is no chaining between messages.
To interoperate you must replicate this exactly: use `IV0` as the IV every time, never the previous
ciphertext block.

## Static values (compiled into the panel firmware)

These are constants baked into the firmware image, **shared across this firmware generation** — they
are not per-device secrets. They were located in the image's read-only data next to the GATT
attribute table, and match the values published by the community project referenced in the root
README. Per-device identity is only the BLE MAC address and the stove serial number (Modbus register
`0x0ADC`).

| Name | Hex (16 bytes) | Role |
|------|----------------|------|
| `KEY1` | `6e296b0bbb1d43f36e47f72e7b6f2e77` | AES-128 key |
| `IV0`  | `da1a557349f25c641b1a368af5b218a7` | fixed CBC IV |
| `TOKEN`| `31dd34512639377b05a2510de725fc75` | plaintext marker; the receiver checks it |

Located in the full flash dump at (see [../panel/disassembly-notes.md](../panel/disassembly-notes.md)):

| Name | File offset in `used_flash_0x0.bin` |
|------|-------------------------------------|
| `TOKEN` | `0x6ce86` |
| `KEY1`  | `0x6ce96` (a second copy in the backup app slot at `0x354ad2`) |
| `IV0`   | `0x1041c` |

## Reference implementation (Python)

Uses the `cryptography` package (`pip install cryptography`).

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY1  = bytes.fromhex("6e296b0bbb1d43f36e47f72e7b6f2e77")
IV0   = bytes.fromhex("da1a557349f25c641b1a368af5b218a7")
TOKEN = bytes.fromhex("31dd34512639377b05a2510de725fc75")

def decrypt(ciphertext: bytes) -> bytes:
    d = Cipher(algorithms.AES(KEY1), modes.CBC(IV0)).decryptor()
    return d.update(ciphertext) + d.finalize()      # fresh IV0 every call

def encrypt(plaintext: bytes) -> bytes:              # plaintext must be a 16-byte multiple
    e = Cipher(algorithms.AES(KEY1), modes.CBC(IV0)).encryptor()
    return e.update(plaintext) + e.finalize()
```

On the ESP32 emulator (MicroPython) the same thing is available through the built-in `cryptolib`:

```python
from cryptolib import aes          # or ucryptolib on older builds
def decrypt(ct): return aes(KEY1, 2, IV0).decrypt(ct)   # mode 2 = CBC
def encrypt(pt): return aes(KEY1, 2, IV0).encrypt(pt)
```

Create a fresh `aes(...)` object per message so the fixed `IV0` is reused rather than chained.

## Worked example

A real, captured UART2 request from the panel (one ~32-byte message, hex):

```
7662d40de8c5654a1c21a859a629ca4523be10fbbdc29dd7da153c39176fcc66
```

Decrypting with `KEY1` / `IV0` yields the plaintext:

```
be130000 31dd34512639377b05a2510de725fc75 014102bc012c fdd4 04040404
└ctr LE─┘ └──────────── TOKEN ───────────┘ └── PDU ───┘ └CRC┘ └─pad─┘
```

- `be130000` — the rolling counter, little-endian (`0x000013be`).
- The 16 `TOKEN` bytes follow and match the constant above (this is how the receiver authenticates
  the message).
- `014102bc012c` — the Modbus PDU (here: read, function `0x41`, register `0x02BC`).
- `fdd4` — the Modbus CRC-16 of the PDU.
- `04040404` — PKCS#7 padding (4 bytes of value `0x04`) up to the 32-byte (2-block) boundary.

The full field-by-field layout, CRC algorithm, and padding rules are in
[frame-format.md](frame-format.md).
