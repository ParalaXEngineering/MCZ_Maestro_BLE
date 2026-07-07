# BLE control protocol (`0xABF0`)

The local control channel. A BLE client connects to the panel and exchanges AES-wrapped Modbus over
a custom GATT service — the same thing the MCZ phone app does at close range, and the path this
project targets for Home Assistant. The message envelope is in [../docs/frame-format.md](../docs/frame-format.md)
and [../docs/aes-encryption.md](../docs/aes-encryption.md); the registers are in
[../docs/modbus-registers.md](../docs/modbus-registers.md).

## GATT layout

The panel advertises as `MCZ_EP<serial>` and exposes:

| UUID | Role |
|------|------|
| `0xABF0` | primary service |
| `0xABF1` | write-no-response — commands **in** |
| `0xABF2` | notify — responses and status pushes **out** |

Negotiate **MTU 517**.

## How control works

1. Scan for `MCZ_EP*`, connect, negotiate MTU, subscribe to notifications on `0xABF2`.
2. To read: send an AES-wrapped `0x03` read PDU to `0xABF1`; the reply arrives on `0xABF2`.
3. To write: send an AES-wrapped `0x06` write PDU to `0xABF1`.
4. The panel also pushes unsolicited status on `0xABF2`, framed with `##` (see the status-broadcast
   section of [../docs/frame-format.md](../docs/frame-format.md)).

The reference implementation of all of this is [`../ble-client/mcz_ble_client.py`](../ble-client/mcz_ble_client.py).

## Pairing / commissioning

- BLE **bonding is required**: Just Works (IO capability NoInputNoOutput), LE Secure Connections,
  bond = yes, MITM = no. The reference client calls `setSecurityAuth(true, false, true)` (bond,
  no-MITM, secure-connections) before connecting; on Linux/BlueZ pass `--pair`.
- **Commissioning:** a stove already bonded to a phone advertises *directed* to that phone only. To
  pair a new device, put the panel in pairing mode — press **+ and −** together, or power-cycle — or
  clear the stored bond (on the bench, wipe NVS; see [README.md](README.md)).

## The readiness gate (why a bench panel refuses connections)

The panel guards the BLE control session behind a **readiness check** in its connect handler. On a
real stove this is satisfied once the panel is talking to a healthy mainboard; on a bare bench board
with nothing on UART2 it is not, so every connect is refused.

Observed on the bench console during a connect attempt:

```
Connect
MA 9c:67:d6:0a:36:6e        <- the connecting device's Bluetooth MAC
rejected Nm0                <- the readiness gate refused the session
disconnected
ADV start                   <- re-advertises, and the client retries
```

The decision logic (addresses in [disassembly-notes.md](disassembly-notes.md)):

- Two status bits in the panel's main state struct must be in the right state (`[+0x54]` bit1 the
  enable bit SET, `[+0x52]` bit2 the fault bit CLEAR). **Correction (2026-07-07):** the enable bit is
  set by the **commissioning/pairing** flow, *not* by successful mainboard communication — the four
  callers of the set site `0x400d2d54` are all provisioning/pairing/UI paths. The fault bit is only
  touched by the BLE-bond path and init, never by mainboard comms. See
  [../docs/ble-readiness-gate-RESOLVED.md](../docs/ble-readiness-gate-RESOLVED.md).
- **After** the gate, the panel consults a small BLE whitelist. When the whitelist is empty
  (count = −1, the state after an NVS wipe), the **first** device to connect is auto-registered and
  accepted — this is how the MCZ app and community ESP32 clients get in the first time. When the
  whitelist has entries, only a matching MAC is accepted (`Found Pair`), others get `rejected Nm0`.

So on the bench there are two things to satisfy in order: **open the readiness gate**, then the
empty whitelist auto-accepts the first client.

**Resolved (2026-07-07):** opening the gate does **not** need a mainboard. GATE1 (`[+0x54]` bit1,
the enable bit) is set by the panel's **commissioning/pairing flow** — the same pairing-mode entry
described just above (`+`/`−` together, or the BLE `CREDENTIALS=` provisioning flow), *not* by any
mainboard reply. GATE2 (`[+0x52]` bit2, the fault bit) is already clear on a fresh, unbonded bench.
So pairing-mode entry is the single action that both opens the gate and (via the empty whitelist)
gets the first client accepted. Full evidence:
[../docs/ble-readiness-gate-RESOLVED.md](../docs/ble-readiness-gate-RESOLVED.md).

## What a bench (no real mainboard) can and cannot validate

- **Can:** advertising, connect, pairing, `0xABF0` discovery, session **accept**, and full encrypted
  register **reads and writes** — all confirmed end-to-end on 2026-07-07 with the gate-open dev-board
  build plus the [mainboard emulator](../stove/emulator/README.md) (connect accepted, `0xABF0`
  enumerated, `read`/`write` round-tripped; evidence in `../captures/gateopen_*.log` and
  [../docs/ble-readiness-gate-RESOLVED.md](../docs/ble-readiness-gate-RESOLVED.md#bench-validation-done-2026-07-07)).
  This confirms the keys/token/CRC/framing and the `0xABF0` read/write paths.
- **Cannot, without a real mainboard:** real register **values** for reads — a read is answered by the
  mainboard, and the emulator returns placeholder data (`state=Off`, `room=0.0 °C`). Validating the
  register map's *meaning* needs the actual stove.
- **Also still open:** whether a **factory-paired, unmodified** panel accepts control the same way as
  the patched dev board (it should — that's the path the MCZ app uses — but it's untested on real
  appliance hardware). The gate-open patch is a bench shortcut, not how a production panel opens.
