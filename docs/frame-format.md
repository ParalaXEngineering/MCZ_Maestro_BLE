# Frame format

Every message on both local links (BLE and UART2) is the same structure: a Modbus PDU wrapped with
a counter and a token, checked with a CRC, padded, and then AES-encrypted. This document specifies
that structure byte-for-byte. The cipher itself is in [aes-encryption.md](aes-encryption.md).

## Plaintext layout (before encryption)

```
offset  size  field
------  ----  ------------------------------------------------------------
  0      4    counter        little-endian, increments once per message
  4     16    TOKEN          constant 31dd34512639377b05a2510de725fc75
 20      N    Modbus PDU     the request or response (see below)
20+N     2    CRC-16         Modbus CRC of the PDU only, appended low byte first
22+N     P    PKCS#7 pad     P = 16 - ((22+N) mod 16), each byte = P
```

The whole thing (`22 + N + P` bytes, always a multiple of 16) is then AES-128-CBC encrypted with
`KEY1` and the fixed `IV0`. On the wire you only ever see the ciphertext.

Key points:
- **counter** — a 32-bit little-endian value that increments by one per message. Observed starting
  points vary; the receiver does not appear to require a specific value, only that it is present.
- **TOKEN** — the constant marker. After decrypting, the receiver checks these 16 bytes; a mismatch
  means "not for me / wrong key" and the message is dropped.
- **CRC-16** — standard Modbus CRC (polynomial `0xA001`), computed over the **PDU only** (not the
  counter or token), appended little-endian (low byte, then high byte).
- **PKCS#7** — if the message is already a 16-byte multiple before padding, a full extra block of
  `0x10` bytes is added (standard PKCS#7).

## The Modbus PDU

Standard Modbus RTU framing, slave address `0x01`:

```
addr  func  ...function-specific...  (no CRC here — the CRC is the envelope's CRC field)
```

Function codes differ by link:

| Link | Read | Write |
|------|------|-------|
| BLE control (`0xABF0`) | `0x03` (standard read holding registers) | `0x06` (write single register) |
| UART2 mainboard link | `0x41` (vendor read) | `0x10` (write multiple registers) |

Request PDU shapes seen in captures:

```
0x03 read     : 01 03 REGhi REGlo CNThi CNTlo
0x06 write    : 01 06 REGhi REGlo VALhi VALlo
0x41 read     : 01 41 REGhi REGlo CNThi CNTlo         (vendor; UART2)
0x10 write    : 01 10 REGhi REGlo QTYhi QTYlo BC data…(standard write-multiple; UART2)
```

See [modbus-registers.md](modbus-registers.md) for the register meanings.

## CRC-16 (Modbus)

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

## Status broadcasts (BLE notify `0xABF2`)

Besides answering reads, the panel pushes unsolicited status on the BLE notify characteristic.
These are framed differently: they start with `## ` (`0x23 0x23 [type] [frag]`), are **fragmented**
(fragment `0x01` first, `0x02` last), and are AES-encrypted with the same key/token. A quick way to
tell a status push from a Modbus reply: a `##` payload length is **never** a multiple of 16, whereas
an AES-Modbus frame always is. After reassembly + decrypt + token check, the payload is a register
image beginning at `0x02BA` (`STATUS_BASE`).

## Worked examples

### UART2 read request (captured)

Ciphertext (32 bytes):
```
7662d40de8c5654a1c21a859a629ca4523be10fbbdc29dd7da153c39176fcc66
```
Plaintext:
```
be130000 | 31dd34512639377b05a2510de725fc75 | 014102bc012c | fdd4 | 04040404
counter    TOKEN                              PDU            CRC    PKCS#7(4)
```
Meaning: read (`0x41`) register `0x02BC`, count `0x012C`.

### UART2 write request (captured)

Plaintext:
```
c3130000 | 31dd…fc75 | 011002c70001020489 | 5641 | 01
counter    TOKEN       PDU                   CRC    PKCS#7(1)
```
Meaning: write-multiple (`0x10`) to register `0x02C7`, quantity 1, byte-count 2, value `0x0489`.

### BLE setpoint write (built by the client, verifiable offline)

`ble-client/mcz_ble_client.py selftest` builds a real "set temperature" frame, encrypts it, then
decrypts and verifies TOKEN + CRC + padding. That path is confirmed correct and is the reference
for the BLE direction.
