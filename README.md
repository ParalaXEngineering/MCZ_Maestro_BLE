# MCZ Maestro+ — local control research

Notes, tools, and a bench emulator for controlling an **MCZ Maestro+ pellet stove**
**locally** from Home Assistant, over the stove's own Bluetooth Low Energy (BLE) interface,
**without modifying the stove** (so the manufacturer warranty stays intact).

This is device-interoperability research on hardware the author owns. It reverse-engineers the
local control protocol of the stove's Wi-Fi/BLE panel so an open-source Home Assistant
integration can talk to it directly, instead of depending on the manufacturer's cloud. It builds
on and cross-checks two public community projects:

- BLE bridge: <https://github.com/foyewmaddeeb/mcz-maestro-ble>
- Cloud-based HA integration: <https://github.com/Robbe-B/maestro_mcz>
- Upstream discussion: <https://github.com/Robbe-B/maestro_mcz/issues/215>

## Scope and intent

- The subject device is **owned by the author**. The firmware image analysed here was read from
  the author's own panel board.
- The goal is **interoperability**: let Home Assistant read status and send the same commands the
  official MCZ app already sends, over the same local BLE channel.
- The **real stove firmware is never modified**. All development is done on **spare ESP32 dev
  boards** that stand in for the stove until the physical unit arrives.
- The AES keys and identifiers documented here are **static values compiled into the panel
  firmware, shared across this firmware generation** (not per-device secrets). They are also
  already published by the community project above. Per-device identity is only the BLE MAC and
  the stove serial number.

## The system in one picture

```
   Home Assistant  ──BLE (local)──►  ┌──────────────┐   UART2 (Modbus,   ┌───────────────┐
   (or MCZ app)                      │  PANEL board │◄──AES-wrapped)────►│  MAINBOARD    │
   ──MQTT (cloud)──►  MCZ cloud ────►│ ESP32 Wi-Fi/ │                    │ (combustion   │
                                     │ BLE HMI      │                    │  controller)  │
                                     └──────────────┘                    └───────────────┘
```

- The **panel** is an ESP32 that bridges two worlds: it talks to the MCZ cloud over MQTT/TLS and
  to the **combustion mainboard** over a UART using Modbus. All stove control is Modbus register
  reads/writes; the panel relays them from either the cloud or the local BLE service.
- **Home Assistant** can drive the panel over BLE, exactly as the MCZ phone app does. That is the
  path this project targets.

## Repository layout

| Path | What's inside |
|------|----------------|
| `docs/` | Cross-cutting protocol specs shared by both interfaces |
| `docs/architecture.md` | System overview, boards, and the three control paths |
| `docs/aes-encryption.md` | The AES-128-CBC scheme, keys, IV, token (with a worked example) |
| `docs/frame-format.md` | Exact byte layout of a message on both BLE and UART2 |
| `docs/modbus-registers.md` | Modbus function codes, register map, state codes |
| `docs/status-and-open-questions.md` | Where the work stands and what's left |
| `docs/ble-readiness-gate-RESOLVED.md` | The readiness gate, resolved: it's a commissioning/pairing gate, not a mainboard one |
| `docs/bench-hardware.md` | The two-board bench rig: board MACs, BLE addresses, backups |
| `panel/` | The ESP32 Wi-Fi/BLE panel: firmware, protocol it exposes, disassembly |
| `panel/README.md` | Panel hardware, partition layout, boot behaviour, flashing |
| `panel/ble-control-protocol.md` | The local BLE control service (`0xABF0`) and its readiness gate |
| `panel/disassembly-notes.md` | Firmware reverse-engineering notes (addresses, findings, tooling) |
| `panel/firmware/` | Flash images and backups (the panel dump and a per-board backup) |
| `panel/tools/` | Firmware analyser and serial-console helpers |
| `stove/` | The combustion mainboard, the panel↔mainboard link, and the cloud path |
| `stove/uart2-mainboard-link.md` | The panel↔mainboard UART protocol (the main new discovery) |
| `stove/cloud-mqtt.md` | The MCZ cloud path, documented for completeness |
| `stove/emulator/` | A bench "mainboard" emulator so the panel works without a real stove |
| `ble-client/` | The Python BLE client (protocol core for the future HA integration) |
| `captures/` | Serial/BLE logs kept as an evidence trail |
| `archive/legacy-notes/` | The original working notes, superseded by `docs/` (kept for history) |

## Quick start

```bash
# Python env (Windows venv used during development; Linux/HA is the eventual target)
python -m pip install -r requirements.txt      # bleak, cryptography, pyserial, esptool

# Prove the BLE protocol core is correct without any hardware:
python ble-client/mcz_ble_client.py selftest
```

To reproduce the bench (panel on one ESP32, mainboard emulator on another), see
[`stove/emulator/README.md`](stove/emulator/README.md) and [`panel/README.md`](panel/README.md).

## Status (2026-07-07)

The local BLE protocol and the panel↔mainboard link are both fully understood, and a bench rig
(panel + emulated mainboard) is standing. The panel's **readiness gate** — the last thing standing
between the bench and a live BLE control session — is now **resolved**: it turned out to be a
**commissioning/pairing** gate, *not* a mainboard-health check, so no UART reply opens it. The
unblock is to put the panel through pairing/provisioning (which sets the enable bit); the mainboard
emulator is already sufficient and its reply is accepted without error. Byte-level evidence and the
exact steps: [`docs/ble-readiness-gate-RESOLVED.md`](docs/ble-readiness-gate-RESOLVED.md). Earlier
framing and reasoning trail: [`docs/status-and-open-questions.md`](docs/status-and-open-questions.md).

**The full BLE control stack is now validated end-to-end on the bench.** Using a gate-open dev-board
build (`panel/tools/patch_open_gate.py`, bench-only), a live panel boots, **accepts** a BLE session
(no `rejected Nm0`), and round-trips **encrypted register reads and writes** through to the mainboard
emulator — proving keys, framing, `0xABF0`, pairing/whitelist, reads and writes on real hardware
(evidence: `captures/gateopen_*.log`). This is a working POC for a **local, cloud-free, BLE-oriented
Home Assistant integration**. What remains is **device-reality validation on the actual stove**:
confirm a factory-paired (unmodified) panel accepts control the same way, and check the register map
against a live mainboard — the bench proves the *protocol*, not the register *values*.
