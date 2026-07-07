# Bringing this into Home Assistant

How this proof of concept could become a local-control feature in the existing
[Robbe-B/maestro_mcz](https://github.com/Robbe-B/maestro_mcz) integration. This is a direction, not a
finished integration — the protocol core is proven; the wiring into HA is the work that remains.

## Where this fits

`maestro_mcz` today controls the stove through the **MCZ cloud** (MQTT). That works but depends on
the internet and MCZ's servers, and it polls slowly. This project proves the same commands and status
can go over the stove's **local BLE** channel instead — no cloud, no stove modification, and fast
local polling. The natural outcome is a **hybrid** integration: keep the cloud path for what only it
provides, add BLE as a local transport for status polling and control.

Upstream discussion: <https://github.com/Robbe-B/maestro_mcz/issues/215>.

## What this POC already provides

- **A validated protocol core** — [`ble-client/mcz_ble_client.py`](../ble-client/mcz_ble_client.py)
  implements the whole local protocol: AES framing, Modbus, the register map, and a status decoder.
  `selftest` proves the crypto/framing offline; the bench run proves reads and writes end-to-end over
  `0xABF0` (see [reference/readiness-gate.md](reference/readiness-gate.md#bench-validation--done-2026-07-07)).
- **The full protocol spec** — [ble-protocol.md](ble-protocol.md) (envelope, frames, registers,
  pairing), so the transport can be reimplemented in any language/runtime HA needs.
- **A known pairing model** — an unmodified panel accepts the first client after entering pairing
  mode; bonding is Just Works + LE Secure Connections.

## Transport options for HA

BLE from Home Assistant can be delivered three ways — in rough order of how HA-native they are:

1. **Native HA Bluetooth** (`bleak` via HA's Bluetooth integration). Runs on a host with a BLE
   adapter. The protocol core here is already `bleak`-based, so this is the most direct port.
2. **ESPHome BLE proxy.** An ESP32 running ESPHome relays BLE to HA over the network — the standard
   way to extend BLE range and avoid needing an adapter on the HA host. The panel's `0xABF0` traffic
   passes through transparently.
3. **Standalone ESP32 → MQTT bridge.** An ESP32 speaks `0xABF0` to the stove and republishes to HA's
   own MQTT — mirrors the community `foyewmaddeeb/mcz-maestro-ble` approach. Most self-contained, but
   another moving part to maintain.

Option 1 or 2 keeps everything inside HA and reuses this client directly.

## The model-profile caveat (why it stays hybrid)

The MCZ app fetches a per-model **profile** from the cloud (which registers/features a given model
exposes) and caches it, then controls over BLE. Raw register read/write doesn't need the profile — it
only decides which registers are meaningful for a model. So a complete integration will likely still
touch the cloud (or ship a static per-model table) for the profile, and use BLE for the actual
polling and control. `maestro_mcz` already knows the cloud side, which is exactly the half this POC
does **not** replace — the two are complementary.

## What's still needed before shipping

1. **Confirm on a real stove** that a factory-paired, unmodified panel accepts local control the same
   way the bench did (it should — it's the path the MCZ app uses — but it's untested on appliance
   hardware). The bench used a gate-open patch as a shortcut; production relies on pairing-mode entry.
2. **Validate the register map against a live mainboard.** The bench reads return the emulator's
   placeholders (`state=Off`, `room=0.0 °C`); real values and the exact `0x41` reply layout need a
   genuine stove.
3. **Map registers to HA entities** — climate (setpoint, mode, power), sensors (temps, fan RPM,
   state, worktime), reusing `maestro_mcz`'s existing entity model where possible.
4. **Decide the profile source** — reuse the cloud fetch, or ship a static table for known models.

## Suggested path to upstream

- Prototype option 1 (native `bleak`) as a local transport behind `maestro_mcz`'s existing entity
  layer, so cloud and BLE are swappable backends.
- Validate on a real stove (steps 1–2 above), refining the register map from live captures.
- Propose it on [issue #215](https://github.com/Robbe-B/maestro_mcz/issues/215) as an optional local
  transport, keeping cloud for the model profile. Credit the community projects this builds on
  (`foyewmaddeeb/mcz-maestro-ble` for the BLE protocol, `Robbe-B/maestro_mcz` for the HA integration).
