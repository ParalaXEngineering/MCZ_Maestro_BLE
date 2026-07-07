# Status and open questions

Snapshot of where the work stands and what is proven. Written so another engineer (or an AI
assistant) can pick up cleanly.

_Last updated: 2026-07-07._

> **Update (2026-07-07, latest): the full BLE control stack is now validated end-to-end on
> the bench.** Using the gate-open dev-board build, a live panel accepts a BLE session and
> round-trips encrypted register reads and writes to the mainboard emulator (details in
> [ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md#bench-validation-done-2026-07-07)).
> The remaining work is **device-reality validation on the actual stove** (confirm a
> factory-paired panel accepts control the same way, and check the register map against a
> real mainboard), plus wrapping the client into a Home Assistant integration.

> **Update (2026-07-07, later session): the "open item" below is RESOLVED and was
> mis-framed.** The BLE readiness gate is a **commissioning / pairing** gate, not a
> mainboard-health gate — **no UART2 reply of any content opens it**, so the hunt for a
> "mainboard ready" register value had no answer to find. Full byte-level evidence and the
> real unblock are in [ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md).
> The section below is kept for the reasoning trail; read it together with the resolution.

## What is done and verified

- **BLE control protocol** — fully understood. Service `0xABF0` (write `0xABF1`, notify `0xABF2`),
  AES-wrapped Modbus. The Python client's `selftest` builds, encrypts, decrypts and verifies a real
  command frame. See [../panel/ble-control-protocol.md](../panel/ble-control-protocol.md).
- **UART2 mainboard link** — fully decoded this session: **115200 8N1**, same AES envelope as BLE,
  vendor function `0x41` (read) / `0x10` (write). The panel's real baud is 115200 even though the
  firmware's config field reads `0xE1000` (a pre-divide value; the effective rate is that ÷8). See
  [../stove/uart2-mainboard-link.md](../stove/uart2-mainboard-link.md).
- **Bench rig** — a panel board (with antenna) and a second ESP32 running a MicroPython mainboard
  emulator, wired together on UART2. The emulator decrypts the panel's requests live and replies.
- **The pipeline works up to the gate** — with the emulator answering, the panel stops its endless
  mainboard-timeout loop and advertises over BLE (`ADV start`). From the laptop, a BLE scan finds
  the panel and a connect attempt **reaches** it (the panel logs the connection and the laptop's
  Bluetooth MAC).
- **Full BLE control validated end-to-end on the bench (2026-07-07)** — using the gate-open dev-board
  build (`panel/tools/patch_open_gate.py`), the whole stack was driven on real hardware: the patched
  image **boots** to `ADV start`, a BLE connect is **accepted** (no `rejected Nm0`), `0xABF0` is
  enumerated, and encrypted register **reads and a write** round-trip through the panel to the
  mainboard emulator and back. This proves the protocol stack (keys/token/CRC/framing/reads/writes)
  on hardware. It is **bench-only** — it does not change how an unmodified panel opens the gate.
  Evidence and detail: [ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md#bench-validation-done-2026-07-07),
  captures `gateopen_*.log`.

## ~~The one open item~~ RESOLVED: the panel's BLE readiness gate

**Resolution:** see [ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md). Short version:
the gate is a **commissioning/pairing** gate. GATE1 (`[+0x54]` bit1, enable) is set only by
provisioning/pairing/UI code; GATE2 (`[+0x52]` bit2, fault) is clear on a fresh bench and is never
set by mainboard comms. The paragraph below reflects the *original hypothesis* ("set only after
successful mainboard communication"), which the firmware **disproves** — the ready flag is a
lifecycle/commissioning event, not a mainboard-comms outcome.

When a BLE client connects, the panel currently answers `rejected Nm0` and drops the link. This is
a deliberate check in the connect handler: it only accepts a control session once an internal
"ready" flag is set. _(Original hypothesis, now disproven: "…set only after the panel has had
genuinely successful communication with the mainboard." In fact it is set by the pairing/provisioning
flow.)_

What was established about it:

- The gate is a runtime check on two status bits in the panel's main state struct (see
  [../panel/disassembly-notes.md](../panel/disassembly-notes.md) for addresses). One enable bit must
  be **set**; one fault bit must be **clear**.
- Merely answering the panel's UART2 polls without errors is **not enough**. A reply that produces
  no error on the panel still leaves the gate closed.
- The panel narrates exactly why each reply is rejected, on its own serial console. This "oracle" is
  the fastest way to iterate:

  | Panel log line | Meaning |
  |----------------|---------|
  | `Timeout N` | no reply received |
  | `No x16 - N` | received length not a multiple of 16 (frame/fragmentation problem) |
  | `CRC Err` | frame received but the Modbus CRC did not validate at the expected boundary |
  | `OtherAddress` | reply had the wrong slave address |
  | `Function Error` | reply had an unexpected function code |
  | `Incomplete Message` | reply shorter than expected |
  | `Exeption: N` | reply was a Modbus exception |

- Findings so far on the response shape:
  - A **short** reply (`[01 41]` + ~20 registers) is accepted with **no errors**, but does not open
    the gate.
  - A **600-byte** reply (300 registers, matching the request's count field) causes `No x16` /
    `CRC Err` — the panel's receive path only cleanly frames short replies; long ones fragment.
  - So the mainboard's real reply is **short**, but the registers that likely signal "ready"
    (fine-state `0x0320`, coarse-phase `0x0322`) sit ~102 registers past the poll's start address —
    beyond where a short reply reaches with all-zero data.

**~~Two intertwined unknowns remain~~ — both dissolved by the resolution:** (1) there is no special
"short reply" to find — the reply the emulator already sends is accepted without a parser error; and
(2) there is **no** register value the panel reads as "mainboard ready" — the enable bit is set by
the commissioning/pairing flow, not by any register read. See
[ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md).

## Recommended next steps

Step 2 below was carried out and **resolved the gate** — see
[ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md). The enable-bit set at
`0x400d2d77` has four callers and **all are provisioning/pairing/UI paths**; GATE2's fault bit
is never set by mainboard comms; and no register value is ever compared to drive the gate. So:

1. **Open the gate by commissioning, not by a reply.** Put the panel into pairing/commissioning
   mode (HMI `+`/`−` together), or drive the BLE text-provisioning `CREDENTIALS=`/`CONNECT` flow.
   That sets `[0x3ffcd224+0x54]` bit1 (the enable). A power-cycle alone does **not**. Details and
   ranking: [ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md#the-real-unblock-what-to-do-on-the-bench).
2. **Keep the emulator running** — it stops the UART timeout and keeps the parser happy, but it is
   not what opens the gate. The reply it already sends is accepted without a parser error.
3. **Confirm end-to-end.** With bit1 set (GATE2 already clear, whitelist empty), the first BLE
   client to connect is auto-registered and accepted; validate reads/writes over `0xABF0`.
   **Done on the bench (2026-07-07)** via the gate-open build — connect accepted, reads and a write
   round-tripped (see [ble-readiness-gate-RESOLVED.md](ble-readiness-gate-RESOLVED.md#bench-validation-done-2026-07-07)).
   Still to do on the **real stove**: confirm a factory-paired panel accepts control the same way
   (no patch), and validate the register map against a live mainboard (bench reads return the
   emulator's placeholder values, not real data).
4. **Wrap into Home Assistant.** `ble-client/mcz_ble_client.py` already holds the protocol core.
   Target either an ESP32 → MQTT bridge or a native HA Bluetooth integration over an ESPHome BLE
   proxy.

### Reproducible firmware tooling (added this session)

- `panel/tools/xdis.py` — robust Xtensa disassembler (capstone desyncs on this image; this steps by
  the Xtensa instruction-length rule and does deterministic `l32r`/`CALL` xref scans).
- `stove/emulator/diagnostics/verify_reply.py` — offline "panel-side" verifier for a candidate reply
  frame (length %16, TOKEN, CRC, register extraction), no hardware needed.

## Client-platform note

BLE **scanning** and **connecting** work from the development laptop (the panel logs the incoming
connection). The historical macOS issues are not relevant here. The eventual production client is
Linux/Home Assistant, which handles BLE bonding transparently.
