# Modbus register map

Stove state and commands are Modbus registers on the combustion mainboard, reached through the
panel. Registers below are verified against a real oven by the community project and cross-checked
against this firmware. Values marked *assumed* still need confirmation on hardware.

The register semantics are the same regardless of which link carries them; only the function codes
differ (see [frame-format.md](frame-format.md)).

## Writes (commands)

Over BLE these use function `0x06` (write single register).

| Register | Meaning | Value |
|----------|---------|-------|
| `0x03F7` | Setpoint temperature | °C × 10 (e.g. `210` = 21.0 °C) |
| `0x03EB` | Power level | 1..5 |
| `0x03E9` | Mode | 0 = Manual, 1 = Auto, 2 = Overnight, 3 = Comfort*, 4 = Turbo* |
| `0x038A` | On/off | write `1` = press the power button (a **toggle**) |
| `0x03FA` | Fan | 1..5 fixed, 6 = auto |
| `0x03EC` | Silent mode | 1 = on, 0 = off |

\* Modes 3/4 are assumed and should be verified against a real stove.

## Reads (status)

Over BLE these use function `0x03` (read holding registers). The app polls the main block as
**read `0x02BC`, count `0x33`** (51 registers).

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

| Code | State |
|------|-------|
| `0x0000` | Off |
| `0x0101` | Cleaning |
| `0x0201` | Loading |
| `0x0301` | Start 1 |
| `0x0401` | Start 2 |
| `0x0501` | Stabilization |
| `0x0601` | Anti-condensation |
| `0x0202` | On |
| `0x0103` | Turning off |

## Note on the UART2 (mainboard) link

The panel↔mainboard link uses **different function codes** than BLE — a vendor read `0x41` and a
standard write-multiple `0x10` — but against the same register space. Observed in captures:

- `01 41 02BC 012C` — the panel's periodic status poll (read starting at `0x02BC`).
- `01 10 02C7 0001 02 0489` — a write-multiple to `0x02C7`.

The exact **response** layout for the vendor `0x41` read is still being pinned down; see
[../stove/uart2-mainboard-link.md](../stove/uart2-mainboard-link.md) and
[status-and-open-questions.md](status-and-open-questions.md).

## Model profiles (why a full HA integration is hybrid)

The MCZ app first fetches a **model profile** from the cloud (which registers/features exist for a
given model) and caches it, then controls over BLE. Raw register read/write does not need the
profile — it only decides which registers are meaningful for a model. A complete Home Assistant
integration is therefore expected to be hybrid: cloud (or a shipped table) for the profile, BLE for
control.
