# Panel ↔ mainboard link — UART2 (reference)

The internal serial link between the panel and the combustion mainboard. It carries the **same
AES-wrapped Modbus** envelope as the BLE channel, just with different function codes over a plain
UART. Decoding it is what makes a bench [mainboard emulator](../../stove/emulator/README.md)
possible. The envelope and crypto are shared with BLE — see [ble-protocol.md](../ble-protocol.md).

## Physical link

| Property | Value |
|----------|-------|
| Panel pins | TX = **GPIO4**, RX = **GPIO5** (`uart_set_pin(UART_NUM_2, 4, 5, -1, -1)`) |
| Framing | **8N1**, no flow control |
| Baud | **115200** (see below) |
| Logic | 3.3 V TTL, idle high |

### The baud: firmware says one thing, the wire says another

The firmware's UART config field decodes to `0xE1000` (= 921600 as a plain integer), but the panel's
**actual emitted bit rate is 115200** — exactly that value ÷ 8. Confirmed two ways: on a scope, clean
frames decode at 115200 and nothing decodes at 921600; in software, reading at 921600 gave only
`0x00`/`0x80` garbage while 115200 produced clean bytes that decrypt correctly. **Use 115200.** The
`0xE1000` value is a pre-divide clock figure, not the line rate.

### Cadence

The panel polls in short **bursts about once per second** (~3 ms active, ~1 s idle), matching its
`Timeout 1` retry cadence when unanswered. An emulated mainboard has a wide, relaxed window to reply
— response timing is not tight.

## Message contents

Each burst is one AES-128-CBC message: `[4B counter][16B TOKEN][Modbus PDU][CRC-16][PKCS#7]` (full
layout in [ble-protocol.md](../ble-protocol.md#frame-format)). Two request types in steady state:

| Captured plaintext PDU | Meaning |
|------------------------|---------|
| `01 41 02BC 012C` | vendor **read** (func `0x41`), register `0x02BC`, count `0x012C` |
| `01 10 02C7 0001 02 0489` | standard **write-multiple** (func `0x10`) to `0x02C7`, qty 1, value `0x0489` |

Function codes differ from BLE (`0x03`/`0x06`): the mainboard link uses vendor read `0x41` and
write-multiple `0x10`. A plain "is-this-Modbus" scan looking for `0x03`/`0x06` finds nothing here —
the payload is Modbus, but with `0x41`.

## Wiring the panel to an emulated mainboard

Two ESP32s, UART2-to-UART2, 3.3 V logic, common ground (no RS-485 transceiver needed):

```
  Panel GPIO4 (TX2) ───────►  Emulator GPIO5 (RX2)
  Panel GPIO5 (RX2) ◄───────  Emulator GPIO4 (TX2)
  Panel GND         ────────  Emulator GND
```

- Keep wires **short** and ground **solid** — a poor common ground corrupts the signal.
- GPIO5 is an ESP32 strapping pin; keep the emulator's TX from driving it low during panel boot, or
  just power the panel first.

## Reply handling

The panel **accepts** the emulator's `0x41` reply without a parser error (correct AES envelope,
TOKEN, CRC, length a multiple of 16). Crucially, **no reply content makes the panel "ready" for
BLE** — the [readiness gate](readiness-gate.md) is a commissioning/pairing gate, not a
mainboard-health check, and reads no mainboard register to decide it. There is no special "ready"
reply to find.

One reply-shape caveat remains: the panel's UART receive path frames **short** replies cleanly but
fragments very long ones (a 300-register / ~640-byte reply logs `No x16`/`CRC Err`). Keep the reply
short. Verify a candidate frame offline (length %16, TOKEN, CRC, register extraction) with
[`diagnostics/verify_reply.py`](../../stove/emulator/diagnostics/verify_reply.py) — no hardware needed.
