# MCZ Maestro+ — local BLE control (proof of concept)

A working proof of concept for controlling an **MCZ Maestro+ pellet stove** locally over its own
**Bluetooth Low Energy** interface — no cloud, no stove modification. The goal is to give the
existing Home Assistant integration [Robbe-B/maestro_mcz](https://github.com/Robbe-B/maestro_mcz) a
**local polling** path to replace (or complement) its current cloud dependency.

The local BLE control stack is **validated end-to-end on a two-board bench**: a live panel accepts a
BLE session and round-trips encrypted register reads and writes. See [Status](#status).

## What this is

`maestro_mcz` controls the stove through the MCZ **cloud** (MQTT) — which needs the internet, MCZ's
servers, and polls slowly. This project reverse-engineers the stove's **local** control protocol so
Home Assistant can talk to it directly over BLE, exactly as the MCZ phone app does at close range.

- **Scope:** interoperability on hardware the author owns. Read status and send the same commands the
  official app sends, over the same local BLE channel.
- **No stove modification.** All development is on spare ESP32 dev boards standing in for the stove
  until the real unit arrives, so the manufacturer warranty stays intact.
- **The keys are not secrets.** The AES keys and identifiers here are **static values compiled into
  the panel firmware, shared across this firmware generation** — not per-device secrets, and already
  published by the community project below. Per-device identity is only the BLE MAC and the stove
  serial number.

Builds on and cross-checks two community projects:

- BLE bridge: <https://github.com/foyewmaddeeb/mcz-maestro-ble>
- Cloud HA integration: <https://github.com/Robbe-B/maestro_mcz>
  ([upstream discussion #215](https://github.com/Robbe-B/maestro_mcz/issues/215))

## The system in one picture

```
   Home Assistant  ──BLE (local)──►  ┌──────────────┐   UART2 (Modbus,   ┌───────────────┐
   (or MCZ app)                      │  PANEL board │◄──AES-wrapped)────►│  MAINBOARD    │
   ──MQTT (cloud)──►  MCZ cloud ────►│ ESP32 Wi-Fi/ │                    │ (combustion   │
                                     │ BLE HMI      │                    │  controller)  │
                                     └──────────────┘                    └───────────────┘
```

The **panel** is an ESP32 that bridges two worlds — the MCZ cloud over MQTT/TLS, and a local BLE
service — down to the **combustion mainboard** over a UART using Modbus. All stove control is Modbus
register reads/writes; the panel just relays them. **Home Assistant can drive the panel over BLE,
exactly as the phone app does** — that's the path this project targets. Full breakdown:
[docs/reference/architecture.md](docs/reference/architecture.md).

## How it was tested

The physical stove wasn't available during development, so the whole pipeline was reproduced on a
bench from a firmware dump:

1. A **flash dump** of a real panel was flashed onto an ESP32 dev board — a live "panel" with no stove
   attached.
2. A **second ESP32** runs a MicroPython **mainboard emulator**, wired to the panel's UART2, answering
   its Modbus polls so the panel behaves as if a stove is attached.
3. A **laptop** drives the panel over BLE with the Python client, exercising the real `0xABF0`
   protocol — reads, writes, pairing, the readiness gate.

This bench proves the **protocol** (keys, framing, service, reads/writes). It does not prove the
register **values** — those come from the emulator's placeholders and need a real mainboard to
confirm. Full recipe: [docs/setup.md](docs/setup.md).

## How it integrates into Home Assistant

The outcome is a **hybrid** integration for `maestro_mcz`: keep the cloud for the per-model profile it
already fetches, add BLE as a fast, local transport for status polling and control. BLE reaches HA
either natively (`bleak`), through an ESPHome BLE proxy, or via an ESP32→MQTT bridge. The protocol
core is already implemented in [`ble-client/mcz_ble_client.py`](ble-client/mcz_ble_client.py). Full
plan and the path to upstream: [docs/integration.md](docs/integration.md).

## Repository layout

| Path | What's inside |
|------|---------------|
| **[docs/setup.md](docs/setup.md)** | Build the bench: flash the panel, run the emulator, wire UART2, drive it from a laptop |
| **[docs/ble-protocol.md](docs/ble-protocol.md)** | **The HA-relevant spec** — GATT `0xABF0`, AES envelope, frames, register map, pairing |
| **[docs/integration.md](docs/integration.md)** | How this becomes local polling in `maestro_mcz` |
| [docs/reference/](docs/reference/) | Internals, for reference and future work — see below |
| [ble-client/](ble-client/) | The Python BLE client (protocol core for the future HA integration) |
| [panel/](panel/) | The ESP32 panel: firmware images, flashing, disassembly tools |
| [stove/emulator/](stove/emulator/) | The bench mainboard emulator (MicroPython) + the diagnostics that decoded the UART2 link |
| [captures/](captures/) | Key serial/BLE logs kept as an evidence trail |

`docs/reference/` (only needed if you want to dig into the firmware or the stove internals):

| Doc | What |
|-----|------|
| [architecture.md](docs/reference/architecture.md) | The three boards and three control paths |
| [uart2-link.md](docs/reference/uart2-link.md) | The internal panel↔mainboard UART2 protocol |
| [readiness-gate.md](docs/reference/readiness-gate.md) | Why a bench panel refuses BLE, and what opens the gate |
| [firmware-disassembly.md](docs/reference/firmware-disassembly.md) | Reverse-engineering notes: addresses, tooling, findings |
| [cloud-mqtt.md](docs/reference/cloud-mqtt.md) | The MCZ cloud path, documented for completeness |

## Quick start

```bash
python -m pip install -r requirements.txt          # bleak, cryptography, pyserial, esptool

# Prove the BLE protocol core is correct with no hardware:
python ble-client/mcz_ble_client.py selftest
```

To reproduce the full bench, follow [docs/setup.md](docs/setup.md).

## Status

_Last updated 2026-07-07._

**The local BLE control stack is validated end-to-end on the bench.** Using a gate-open dev-board
build (bench-only), a live panel boots, **accepts** a BLE session (no `rejected Nm0`), and round-trips
**encrypted register reads and writes** through to the mainboard emulator — proving keys, framing,
`0xABF0`, pairing/whitelist, and reads/writes on real hardware (evidence: `captures/gateopen_*.log`).

Along the way, two things were fully decoded: the BLE control protocol, and the internal
panel↔mainboard UART2 link (same AES envelope, different function codes). The panel's **readiness
gate** — the last blocker — turned out to be a **commissioning/pairing** gate, not a mainboard-health
check: entering pairing mode opens it, and no mainboard reply is needed. Details:
[docs/reference/readiness-gate.md](docs/reference/readiness-gate.md).

**What remains is device-reality validation on the actual stove:** confirm a factory-paired
(unmodified) panel accepts control the same way, and check the register map against a live mainboard.
The bench proves the *protocol*; it does not prove the register *values*.
