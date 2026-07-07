# The BLE readiness gate (reference)

Why a bench panel refuses BLE control sessions, and what actually opens the gate. Resolved
2026-07-07 by static analysis of `panel/firmware/used_flash_0x0.bin`.

## Headline

**The panel's BLE readiness gate is a commissioning / pairing gate, not a mainboard-health gate. No
UART2 mainboard reply — of any length or register content — can open it.** The mainboard emulator is
already sufficient; the panel accepts its replies without a parser error. What keeps BLE control
refused on the bench is that the panel has never been through the pairing/commissioning flow that
sets its internal "enable" bit.

So the once-open question "which register value does the panel read as *mainboard ready*" has **no
answer, because no such read exists.**

## The gate, decoded

Connect handler at `0x400d26ae` (prints `Connect`). State struct base `0x3ffcd224`. Two-part gate:

```
0x400d26bd  l8ui   a8, a2, 0x54     ; a8 = [state+0x54]
0x400d26c0  bbsi   a8, 1, +6        ; GATE1: bit1 SET  -> continue
0x400d26c3  j      0x400d2ab8       ;        else      -> reject
0x400d26c6  l16ui  a8, a2, 0x52     ; a8 = [state+0x52]
0x400d26c9  bbci   a8, 2, +6        ; GATE2: bit2 CLEAR -> continue
0x400d26cc  j      0x400d2ab8       ;        else       -> reject
0x400d26cf  ...                     ; both pass -> whitelist logic
```

- **GATE1** — `[state+0x54]` **bit1 (0x02) must be SET** (an "enable" bit).
- **GATE2** — `[state+0x52]` **bit2 (0x04) must be CLEAR** (a "fault" bit).
- Both failures jump to the shared reject block `0x400d2ab8`, which prints `rejected Nm0`. Only after
  **both** gates pass does the handler consult the whitelist; with the whitelist empty
  (`Dev: -1 - 4354`) the first client is auto-registered and accepted.

## Why the mainboard cannot open it

**GATE1's enable bit is set only by commissioning/pairing code.** `[state+0x54] |= 2` is executed
unconditionally at the tail of `0x400d2d54` (store at `0x400d2d77`), so the *caller* decides
readiness. There are exactly four callers, and **every one is a provisioning / pairing / UI path —
none is the mainboard poll:**

| Caller | Context | Enables on the bench? |
|--------|---------|-----------------------|
| `0x400d2fe0` (BLE task start) | Guard skips the enable block unless arg==0; its sole caller passes `a10=1`. | No — block skipped |
| `0x400d828e` | Panel **UI / pairing state machine** (dispatch on UI-state global `0x3ffc67a0`). | Only in pairing UI states |
| `0x400eab55` | **`Got credentials`** — Wi-Fi provisioning; reads NVS key `RST_PARAM`, gated on `[state+0x61]`. | Only during Wi-Fi provisioning |
| `0x400eada9` | **`Menu resetParam`** — pairing/reset menu callback. | Only via the reset menu |

**GATE2's fault bit is never set by mainboard comms.** Exhaustive scan of stores to `[state+0x52]`:
init clears the word; several sites touch other bits; the UART parser **success** path clears bits
8–9; the gated **bit2** is set **only** by the BLE-bonding path (`0x400d2a18`, after `Already saved`)
and cleared at init and in the supervisor. A UART2 timeout does not set it; a successful reply
doesn't touch it. On a fresh, unbonded bench, bit2 is 0 — **GATE2 is already open.**

**No register value is ever compared to drive the gate.** There is no load-of-a-mainboard-register
feeding a compare on the accept path. The parsed register image feeds display and the MQTT/app
supervisor only — never the BLE accept decision.

## What the bench symptom proves

NVS erased → whitelist empty (`Dev: -1 - 4354`); no prior bond → GATE2 open. If GATE1 were set, an
empty whitelist would **auto-accept** the first client. It doesn't — every connect is `rejected Nm0`.
So GATE1 is not set, and since whitelist entries are only added *after* the gates pass, it can never
self-heal from BLE traffic alone. The blocker is unambiguously the commissioning enable bit.

## The real unblock

Keep the emulator running (it stops the UART timeout and keeps the parser happy), then set GATE1's
enable bit by driving one of the commissioning paths, in rough order of bench practicality:

1. **Enter pairing mode on the panel HMI** — `+` and `−` buttons together. This drives the UI/pairing
   state machine into a state that calls `0x400d2d54`. A plain power-cycle is **not** enough.
2. **Drive the BLE text-provisioning service** (separate from `0xABF0`; field separator `0xB4`): the
   `CREDENTIALS=<ssid>\xB4<pass>` / `CONNECT` flow routes through `Got credentials`. BLE-only, no
   buttons — the path the MCZ app uses on first setup. Note the `[state+0x61]` pre-gate.
3. **Confirm directly** — read `[0x3ffcd224 + 0x54]` bit1 at connect time (JTAG/gdb, or a one-line
   temporary log on a *scratch* build — never the warranty board) and watch it flip 0→1 on entering
   pairing.

Once bit1 is set (GATE2 clear, whitelist empty), the first `0xABF0` client is auto-registered and
accepted — the outcome the project targets.

## Bench shortcut: gate-open build

For end-to-end validation of the BLE stack *now*, the bench "panel" (a spare dev board, not the
appliance) can simply bypass the gate. [`panel/tools/patch_open_gate.py`](../../panel/tools/patch_open_gate.py)
rewrites one instruction at `0x400d26bd` (`l8ui a8,[state+0x54]` → `j 0x400d26cf`, skipping both
checks into the whitelist auto-accept) and recomputes the image's checksum + SHA-256. Procedure:
[`panel/firmware/flash_4mb/README.md`](../../panel/firmware/flash_4mb/README.md#1b-optional-gate-open-build--to-actually-test-ble-control-on-the-bench).
This proves keys/framing/`0xABF0`/reads/writes work; it is **bench-only** and does not substitute for
the real commissioning trigger on an unmodified panel.

## Bench validation — done (2026-07-07)

The gate-open build was flashed to the panel board and driven end-to-end. All stages passed on real
hardware:

- **The patched image boots** (the one thing static analysis couldn't prove): clean `POWERON_RESET` →
  `Letto resetParam 0` → `Dev: -1 - 4354` → `Found RE 0` → `ADV start`. No bootloop; the recomputed
  checksum/SHA is accepted by the 2nd-stage bootloader.
- **Connect is accepted** — the panel logs `Connect`, holds a ~19 s session, then a clean
  `disconnected`. **No `rejected Nm0`** (contrast the stock app's reject loop in
  `captures/panel_connect_test.log`).
- **`0xABF0` works end-to-end** — the client enumerates the full GATT DB, subscribes to `0xABF2`, and
  round-trips **encrypted register reads** and an **encrypted write** (`0x03F7 ← 210`, set 21.0 °C)
  through the panel to the mainboard emulator and back. The emulator answers the 1 Hz polls throughout.

This validates the whole BLE control **stack** — AES keys, token, CRC, framing, `0xABF0`, whitelist
auto-accept, reads, writes. The register *values* returned are the emulator's defaults
(`state=Off`, `room=0.0 °C`), not real stove data — it validates the path, not the data. Evidence:
`captures/gateopen_panel_console.log`, `captures/gateopen_ble_session.log`,
`captures/gateopen_emulator.log`. Revert the dev board with `write_flash 0x10000 app_ota0.bin`.

## Reproducing the analysis

- [`panel/tools/xdis.py`](../../panel/tools/xdis.py) — robust Xtensa disassembler (capstone's Xtensa
  backend desyncs on this image). Commands: `dis`, `at`, `bytes`, `xref`.
- [`stove/emulator/diagnostics/verify_reply.py`](../../stove/emulator/diagnostics/verify_reply.py) —
  offline "panel-side" verifier for a candidate reply frame, no hardware.

Both need a venv with `pip install --pre 'capstone>=6.0'` and `cryptography`:

```bash
python panel/tools/xdis.py at 0x400d2d77 0x40 0x18      # the enable-bit set site
python panel/tools/xdis.py xref 0x3ffcd224              # who touches the state struct
python stove/emulator/diagnostics/verify_reply.py       # check the emulator's reply frame
```
