# Cloud path (MQTT)

Documented for completeness. This is the manufacturer's default control path — the panel connects
out to the MCZ cloud broker over MQTT/TLS. **This project deliberately does not depend on it**; the
goal is local BLE control (see [../panel/ble-control-protocol.md](../panel/ble-control-protocol.md)).
It is described here only so the full picture is captured and so it is clear why the local path is
preferred.

Values were recovered by disassembling the `esp_mqtt_client_config_t` the panel builds at
`0x400d5049` (see [../panel/disassembly-notes.md](../panel/disassembly-notes.md)).

## Broker and TLS

| Field | Value |
|-------|-------|
| Broker URI | `mqtts://m.maestro.mcz.it` |
| Port | `8883` |
| TLS trust | a single **pinned CA** = DigiCert TLS RSA SHA256 2020 CA1 (saved as `../panel/firmware/mcz_broker_ca_digicert.pem`) |
| Hostname check | `skip_cert_common_name_check = 0` → the hostname **is** verified |
| Client cert | none — the broker uses username/password auth, not mTLS |
| Username / client id | the stove **serial number** (set at runtime) |
| Firmware update host | `https://f.maestro.mcz.it/hlapi/v1.0/Firmware/Download/…` (same DigiCert CA) |

### The config struct as built in firmware (`0x400d5049`)

Field offsets of the `esp_mqtt_client_config_t`:

| Offset | Field | Value |
|--------|-------|-------|
| 0  | `broker.address.uri` | `mqtts://m.maestro.mcz.it` |
| 16 | `broker.address.port` | `8883` |
| 28 | `broker.verification.certificate` | DigiCert CA PEM |
| 40 | `skip_cert_common_name_check` | `0` (hostname **is** checked) |
| 52 / 56 | `username` / `client_id` | device serial number (set at runtime) |
| 64 | `authentication.password` | the shared password below |

Because both the CA chain **and** the hostname are verified, the cloud connection cannot be
redirected to a local broker by DNS alone — doing so would require modifying the panel firmware
(changing the pinned URI/CA), which this project avoids. That constraint is a large part of *why*
the local BLE path is the chosen approach.

## Topics

`%s` = the stove serial number:

- `MCZ/<serial>/0/control` — commands in
- `MCZ/<serial>/0/status` — state out
- `MCZ/<serial>/0/nvm` — parameter / NVM access
- `MCZ/<serial>/0/test`, `MCZ/<serial>/0/test/ack` — factory / test mode
- `MCZ/<serial>/0/component-info`

## Authentication note

The panel authenticates to the broker with the device serial number as the username and a **static
password that is compiled into the firmware and shared across this firmware generation**
(`z0;2U;K3u#Y1`). It is not a per-device secret; it is already documented in the public community
discussion referenced in the root README. It is recorded here for completeness of the analysis.
Treat it as a shared vendor credential. This project does not use the cloud path, so it does not rely
on this value.
