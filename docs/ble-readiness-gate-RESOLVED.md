# The BLE readiness gate — RESOLVED

_Resolved 2026-07-07 by static analysis of `panel/firmware/used_flash_0x0.bin`. This
supersedes the "find the mainboard reply that opens the gate" framing in
[status-and-open-questions.md](status-and-open-questions.md)._

## Headline

**The panel's BLE readiness gate is a commissioning / pairing gate, not a
mainboard-health gate. No UART2 mainboard reply — of any length or register content —
can open it.** The mainboard emulator is already sufficient: the panel accepts its
replies without a parser error. What keeps BLE control refused on the bench is that the
panel has never been through the pairing/commissioning flow that sets its internal
"enable" bit.

This means the previous open item ("which register value does the panel read as
*mainboard ready*") has **no answer, because no such read exists**. The search was a
dead end, and this document explains why with byte-level evidence, then gives the real
unblock.

## The gate, decoded

Connect handler at `0x400d26ae` (prints `Connect`). State struct base `0x3ffcd224`
(loaded into `a2`). The two-part gate:

```
0x400d26bd  l8ui   a8, a2, 0x54     [82 02 54]   ; a8 = [state+0x54]
0x400d26c0  bbsi   a8, 1, +6        [17 e8 02]   ; GATE1: bit1 SET  -> continue
0x400d26c3  j      0x400d2ab8       [46 fc 00]   ;        else      -> reject
0x400d26c6  l16ui  a8, a2, 0x52     [82 12 29]   ; a8 = [state+0x52]
0x400d26c9  bbci   a8, 2, +6        [27 68 02]   ; GATE2: bit2 CLEAR -> continue
0x400d26cc  j      0x400d2ab8       [06 fa 00]   ;        else       -> reject
0x400d26cf  ...                                  ; both pass -> whitelist logic
```

- **GATE1** — `[state+0x54]` **bit1 (0x02) must be SET** (an "enable" bit).
- **GATE2** — `[state+0x52]` **bit2 (0x04) must be CLEAR** (a "fault" bit).
- Both failure jumps land on the shared reject block `0x400d2ab8`, which prints
  `rejected Nm0`. Only after **both** gates pass does the handler consult the whitelist;
  with the whitelist empty (`Dev: -1 - 4354`) the first client would be auto-registered
  and accepted.

(Gate decode independently re-derived from raw bytes by three verifiers — CONFIRMED.)

## Why the mainboard cannot open it

### GATE1's enable bit is set only by commissioning/pairing code

`[state+0x54] |= 2` is executed at the tail of the function at **`0x400d2d54`**:

```
0x400d2d6f  movi.n a10, 2           [0c 2a]
0x400d2d71  l8ui   a8, a9, 0x54     [82 09 54]   ; a9 = 0x3ffcd224
0x400d2d74  or     a8, a8, a10      [a0 88 20]
0x400d2d77  s8i    a8, a9, 0x54     [82 49 54]   ; set bit1, unconditionally
0x400d2d7a  retw.n                  [1d f0]
```

It is unconditional, so the *caller* decides readiness. There are exactly four callers,
and **every one is a provisioning / pairing / UI path — none is the mainboard poll**:

| Caller | Context | Sets enable on the bench? |
|--------|---------|---------------------------|
| `0x400d2fe0` (fn `0x400d2fd4`) | BLE task start (`spp_cmd_task`). Guard `bnez a2,+0x3e` skips the enable block unless arg==0; its sole caller `0x400e9346` passes `a10=1` (`movi a10,1` @`0x400e9343`). | **No** — arg is always 1, block skipped |
| `0x400d828e` (fn `0x400d80bc`) | Panel **UI / pairing state machine**, dispatching on UI-state global `0x3ffc67a0` against pairing state codes (0x10/0x20/2/3/…). Enable is reached only in specific UI/pairing states. | Only in pairing UI states |
| `0x400eab55` (fn ~`0x400eaae8`) | **`Got credentials`** — Wi-Fi provisioning handler; reads NVS key `RST_PARAM` (`Letto resetParam %d`), gated on `[state+0x61]!=0` (set by the `RST_WIFI` routine `0x400e8dc8`). | Only during Wi-Fi provisioning |
| `0x400eada9` (fn `0x400eaae8`) | **`Menu resetParam`** — pairing/reset menu callback (dispatch table `0x400ebff8`). | Only via the reset menu |

`Letto resetParam %d` reads from **NVS** (key `RST_PARAM`, via nvs_get at `0x400eabdf`),
not from a Modbus register — so even the `resetParam` path is not a UART trigger.

### GATE2's fault bit is never set by mainboard comms

Exhaustive scan of every store to `[state+0x52]`:

| Site | Effect |
|------|--------|
| `0x400ec227` (boot init) | writes 0 (clears the whole word, incl. bit2) |
| `0x400d2657` / `0x400d2cb1` / `0x400d2e26` | manipulate **bit7 (0x80)** |
| `0x400d36cd` (UART parser **success**) | clears **bits 0x300 (bits 8,9)**, sets `[+0x60]=1` |
| `0x400eb114` | sets **bits 0x300**, gated on `[+0x54]` bit5 |
| `0x400eb46c–71` | `and a8,a8,~4` → clears **bit2** |
| `0x400d2a18` (BLE **bond** path, after `Already saved`) | `or …,4` → sets **bit2** |

Bit2 (the gated bit) is set **only** by the BLE-bonding path and is cleared at init and
in the supervisor. A UART2 **timeout** does not set it (it only zeroes `[+0x60]` and
bumps the error counter `[+0x62]`); a **successful** reply does not touch it. On a
fresh, unbonded bench bit2 is 0, so **GATE2 is already open**.

### No register value is ever compared to drive the gate

There is no `l16ui`-of-a-mainboard-register feeding a compare-to-constant anywhere on
the accept path. The parsed register image (raw PDU buffer, and the display/command
mirrors at `0x3ffcc6d0` / `0x3ffcc7cc`) feeds **display and the MQTT/app supervisor
only** — never the BLE accept decision. (Independently CONFIRMED by two verifiers.)

## What the bench symptom actually proves

On the bench: NVS erased → whitelist count = `-1` (empty, per `Dev: -1 - 4354`); no
prior bond → GATE2 bit2 = 0 (open). If GATE1 were set, an empty whitelist would
**auto-accept** the first client. It does not — every connect is `rejected Nm0`.
Therefore **GATE1 is not set**, and (because entries are only added *after* the gates
pass) it can never self-heal from BLE traffic alone. The blocker is unambiguously the
commissioning enable bit.

## The real unblock (what to do on the bench)

The mainboard emulator stays (it stops the endless UART timeout and keeps the parser
happy), but to open BLE control you must set GATE1's enable bit by driving one of the
commissioning paths above. In rough order of bench practicality:

1. **Enter pairing / commissioning mode on the panel HMI** — the `+` and `−` buttons
   together (the mechanism already noted in
   [../panel/ble-control-protocol.md](../panel/ble-control-protocol.md)). This drives the
   UI/pairing state machine (`0x3ffc67a0`) into a state that calls `0x400d2d54`. A plain
   power-cycle is **not** enough (the boot log shows the gate still shut after
   `POWERON_RESET`).
2. **Drive the BLE text-provisioning service** (separate from `0xABF0`; field separator
   `0xB4`): the `CREDENTIALS=<ssid>\xB4<pass>` / `CONNECT` flow routes through
   `Got credentials`. This is BLE-only (no physical buttons) and is the path the MCZ app
   uses on first setup. Note the `[state+0x61]` pre-gate (set by the `RST_WIFI` routine).
3. **Confirm the mechanism directly**: read `[0x3ffcd224 + 0x54]` bit1 at connect time
   (JTAG/gdb, or a one-line temporary log on a *scratch* build — never the warranty
   board). Watch it flip from 0 to 1 the moment you enter pairing/provisioning.

Once bit1 is set (and GATE2 clear, whitelist empty), the first `0xABF0` client is
auto-registered and accepted — the outcome the project targets.

### Bench shortcut: patch the dev board to validate the BLE stack now

The bench "panel" is a spare ESP32 dev board (not the appliance), so for end-to-end
validation of the BLE control implementation you can simply bypass the gate on that board.
`panel/tools/patch_open_gate.py` rewrites one instruction at `0x400d26bd`
(`l8ui a8,[state+0x54]` → `j 0x400d26cf`, skipping both gate checks into the whitelist
auto-accept) and recomputes the app image's checksum + SHA-256. Procedure and test commands:
[../panel/firmware/flash_4mb/README.md](../panel/firmware/flash_4mb/README.md#1b-optional-gate-open-build--to-actually-test-ble-control-on-the-bench).
This proves keys/framing/`0xABF0`/pairing/reads/writes work; it does **not** substitute for
the real commissioning trigger on an unmodified panel.

### Bench validation — DONE (2026-07-07)

The gate-open build was flashed to the panel board (COM39) and driven end-to-end. **All
stages passed on real hardware:**

- **The patched image boots** (this was the one thing static analysis could not prove).
  Clean `POWERON_RESET` → `Letto resetParam 0` → `Dev: -1 - 4354` (empty whitelist, NVS
  erased) → `Found RE 0` → `ADV start`. No bootloop. The checksum/SHA recompute is accepted
  by the 2nd-stage bootloader.
- **Connect is accepted — the gate is bypassed.** The panel logs `Connect` and holds a
  ~19 s session, then a clean `disconnected`. **No `rejected Nm0`** — the exact contrast
  with the stock app's reject loop in `captures/panel_connect_test.log`.
- **`0xABF0` works end-to-end.** From the laptop, the client enumerates the full GATT DB,
  subscribes to `0xABF2`/`0xABF4`, and round-trips **encrypted register reads** (panel →
  UART2 → mainboard emulator → panel → BLE notify) and an **encrypted write**
  (`0x03F7 ← 210`, set 21.0 °C). The emulator answers the panel's 1 Hz polls throughout.

This validates the whole BLE control **stack** — AES keys, token, CRC, framing, the `0xABF0`
service, whitelist auto-accept, reads, and writes. The register *values* returned are the
emulator's defaults (`state=Off`, `room=0.0 °C`), not real stove data — it validates the
path, not the data. Evidence: `captures/gateopen_panel_console.log`,
`captures/gateopen_ble_session.log`, `captures/gateopen_emulator.log`.

**Still bench-only.** This does not change how a real, unmodified panel opens the gate —
that remains the commissioning/pairing trigger described below. Revert the dev board with
`write_flash 0x10000 app_ota0.bin`.

## Reproducing this analysis

- `panel/tools/xdis.py` — robust Xtensa disassembler. Capstone's Xtensa backend desyncs
  on this image (emits bogus ESP32-S3 `ee.*` vector ops); `xdis.py` steps by the Xtensa
  instruction-length rule and only uses capstone to render one sized instruction. It also
  does deterministic `l32r`/`CALL` xref scans. Commands: `dis`, `at`, `bytes`, `xref`.
- `stove/emulator/diagnostics/verify_reply.py` — offline "panel-side" verifier: mirrors
  the panel's own checks (length %16 → `No x16`, TOKEN, CRC → `CRC Err`) on a candidate
  reply and extracts named registers, with no hardware.

Both need a venv with `pip install --pre 'capstone>=6.0'` and `cryptography`. Example:

```bash
python panel/tools/xdis.py at 0x400d2d77 0x40 0x18      # the enable-bit set site
python panel/tools/xdis.py xref 0x3ffcd224              # who touches the state struct
python stove/emulator/diagnostics/verify_reply.py       # check the emulator's reply frame
```
