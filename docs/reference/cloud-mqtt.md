# Cloud path — MQTT (reference)

Documented for completeness only. This is the manufacturer's default control path: the panel
connects out to the MCZ cloud broker over MQTT/TLS. **This project deliberately does not use it** —
the goal is local BLE control (see [ble-protocol.md](../ble-protocol.md)). It's described here so the
full picture is captured, and to show *why* the local path is the chosen one.

Values were recovered by disassembling the `esp_mqtt_client_config_t` the panel builds at
`0x400d5049` (see [firmware-disassembly.md](firmware-disassembly.md)).

## Broker and TLS

| Field | Value |
|-------|-------|
| Broker URI | `mqtts://m.maestro.mcz.it` |
| Port | `8883` |
| TLS trust | a single **pinned CA** = DigiCert TLS RSA SHA256 2020 CA1 (`../../panel/firmware/mcz_broker_ca_digicert.pem`) |
| Hostname check | `skip_cert_common_name_check = 0` → the hostname **is** verified |
| Client cert | none — the broker uses username/password auth, not mTLS |
| Username / client id | the stove **serial number** (set at runtime) |
| Firmware update host | `https://f.maestro.mcz.it/hlapi/v1.0/Firmware/Download/…` (same CA) |

Because both the CA chain **and** the hostname are verified, the cloud connection cannot be
redirected to a local broker by DNS alone — that would require modifying the panel firmware (changing
the pinned URI/CA), which this project avoids. That constraint is a large part of *why* local BLE is
the chosen approach.

## Topics

`%s` = the stove serial number:

- `MCZ/<serial>/0/control` — commands in
- `MCZ/<serial>/0/status` — state out
- `MCZ/<serial>/0/nvm` — parameter / NVM access
- `MCZ/<serial>/0/test`, `MCZ/<serial>/0/test/ack` — factory / test mode
- `MCZ/<serial>/0/component-info`

## Authentication note

The panel authenticates with the device serial number as username and a **static password compiled
into the firmware, shared across this firmware generation** (`z0;2U;K3u#Y1`) — not a per-device
secret, and already documented in the public community discussion linked from the root README.
Recorded here only for completeness; this project does not use the cloud path.
