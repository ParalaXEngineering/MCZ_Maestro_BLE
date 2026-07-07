# Panel ↔ mainboard link (UART2)

The internal serial link between the panel and the combustion mainboard. Decoding it was the main
result of the 2026-07-07 session: it turns out to carry the **same AES-wrapped Modbus** envelope as
the BLE channel, just with different function codes and over a plain UART. Understanding it is what
makes a bench mainboard [emulator](emulator/README.md) possible.

The message envelope and crypto are shared with BLE — see [../docs/frame-format.md](../docs/frame-format.md)
and [../docs/aes-encryption.md](../docs/aes-encryption.md).

## Physical link

| Property | Value |
|----------|-------|
| Panel pins | TX = **GPIO4**, RX = **GPIO5** (from `uart_set_pin(UART_NUM_2, 4, 5, -1, -1)`) |
| Framing | **8N1**, no flow control |
| Baud | **115200** (see the note below) |
| Logic | 3.3 V TTL, idle high |

### The baud: firmware says one thing, the wire says another

The firmware's UART config field decodes to `0xE1000` (= 921600 as a plain integer). But the panel's
**actual emitted bit rate is 115200** — exactly that value ÷ 8. This was confirmed two ways:

1. **On a scope:** clean, error-free UART frames decode at 115200 (and at 125000); nothing decodes
   at 921600 (only `0x00`/`0x80` noise).
2. **In software:** reading the line with an ESP32 UART at 921600 produced only `0x00`/`0x80`
   garbage; a baud sweep plus edge-timing measurements pointed low, and 115200 produced clean,
   consistently-structured bytes that decrypt correctly.

**Use 115200 for interop.** The `0xE1000` value is a pre-divide clock figure, not the line rate.

### Cadence

The panel polls the mainboard as short **bursts about once per second** (matching its `Timeout 1`
retry cadence when unanswered): ~3 ms of activity, then ~1 s idle. This gives an emulated mainboard a
wide, relaxed window to reply in — response timing is not tight.

## Message contents

Each burst is one AES-128-CBC message: `[4B counter][16B TOKEN][Modbus PDU][CRC-16][PKCS#7]`
(full layout in [../docs/frame-format.md](../docs/frame-format.md)). The counter increments once per
message; the token is the shared constant.

Two request types were observed in steady state:

| Captured plaintext PDU | Meaning |
|------------------------|---------|
| `01 41 02BC 012C` | vendor **read** (func `0x41`), register `0x02BC`, count field `0x012C` |
| `01 10 02C7 0001 02 0489` | standard **write-multiple** (func `0x10`) to `0x02C7`, qty 1, value `0x0489` |

Note the function codes differ from BLE (`0x03`/`0x06`): the mainboard link uses a **vendor read
`0x41`** and standard **write-multiple `0x10`**. This is why a plain "is-this-Modbus" scan looking
for `0x03`/`0x06` finds nothing on this link — the payload is Modbus, but with `0x41`.

## Wiring the panel to an emulated mainboard

Two ESP32 boards, UART2-to-UART2, 3.3 V logic, common ground (no RS-485 transceiver needed between
two ESP32s):

```
   Panel GPIO4 (TX2) ───────────────►  Emulator GPIO5 (RX2)
   Panel GPIO5 (RX2) ◄───────────────  Emulator GPIO4 (TX2)
   Panel GND         ─────────────────  Emulator GND
```

Notes:
- Keep the wires **short** and the ground **solid**. A poor common ground or long leads corrupt the
  signal (the emulator's receive path only cleanly frames short replies as it is).
- GPIO5 is an ESP32 strapping pin; keep the emulator's TX from driving it low during the panel's
  boot, or just power the panel first.

## Reading / replying to this link (reference)

The [emulator](emulator/README.md) does exactly this: it opens UART2 at 115200 8N1 on GPIO4/5,
decrypts each burst, checks the token, parses the Modbus PDU, builds a reply PDU, re-wraps it in the
same AES envelope, and transmits it. The diagnostics in `emulator/diagnostics/` are the scripts used
to discover all of the above (baud sweeps, edge-timing, decryption, request enumeration).

## Reply handling — resolved

The panel **accepts** the emulator's `0x41` reply without a parser error (correct AES envelope,
TOKEN, CRC, and a length that is a multiple of 16). Crucially, **no reply content makes the panel
"ready" for BLE**: the BLE readiness gate is a commissioning/pairing gate, not a mainboard-health
check, and reads no mainboard register to decide it. So there is no special short reply or "ready"
register value to discover here — that earlier open question was mis-framed. Full evidence and the
real unblock: [../docs/ble-readiness-gate-RESOLVED.md](../docs/ble-readiness-gate-RESOLVED.md).

You can verify a candidate reply frame offline (length %16, TOKEN, CRC, register extraction) with
[`emulator/diagnostics/verify_reply.py`](emulator/diagnostics/verify_reply.py) — no hardware needed.

The one genuine reply-shape caveat that remains bench-testable: the panel's UART receive path frames
**short** replies cleanly but fragments very long ones (a 300-register / ~640-byte reply logged
`No x16`/`CRC Err`). Since reply content does not gate BLE, keep the reply short; refine its exact
register layout against a real mainboard capture only if/when accurate BLE **reads** are needed.
