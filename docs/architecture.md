# System architecture

How an MCZ Maestro+ stove is put together, and the three ways to control it. This frames every
other document: the crypto, the frames, and the register map are all in service of talking to the
**panel**, which relays to the **mainboard**.

## The three boards

| Board | What it is | Interfaces |
|-------|------------|------------|
| **Combustion mainboard** | Runs the actual stove (auger, fans, igniter, safety). Holds the live register state. | Modbus **slave** on a UART |
| **Panel (HMI)** | ESP32 Wi-Fi/BLE controller with the touch display. Bridges cloud/BLE ⇄ mainboard. | Wi-Fi, BLE, and Modbus **master** on UART2 |
| *(external)* Phone / HA / cloud | The controllers that drive the panel | BLE or MQTT |

The example unit is an MCZ "RAY Comfort Air 8 XUP" Maestro+ (an M2-series stove). The panel's full
version string is `M2S.AIR.24.20, Panel:16`.

## The panel is a relay, not the brain

All stove control is **Modbus register reads and writes** against the mainboard. The panel never
decides stove behaviour on its own; it just relays register operations from whichever controller is
talking to it:

```
                      ┌──────────────────────── PANEL (ESP32) ───────────────────────┐
   BLE client  ─────► │  BLE GATT service 0xABF0  ─┐                                   │
   (HA / app)         │                            ├─► Modbus master ─► UART2 ─► mainboard
   MQTT (cloud) ────► │  MQTT client (m.maestro…)  ─┘        (AES-wrapped Modbus)      │
                      └───────────────────────────────────────────────────────────────┘
```

Both the BLE service and the cloud client ultimately turn into the **same** Modbus traffic toward
the mainboard. That is why understanding the Modbus register map (see
[modbus-registers.md](modbus-registers.md)) is enough to control everything.

## A surprising symmetry: the same crypto on two links

The two local links use the **same** message envelope — AES-128-CBC wrapping a Modbus PDU, with a
shared token and a rolling counter:

| Link | Transport | Baud / MTU | Modbus function codes | Who answers |
|------|-----------|-----------|-----------------------|-------------|
| **BLE control** | GATT `0xABF0` (write `0xABF1`, notify `0xABF2`) | MTU 517 | `0x03` read / `0x06` write | the panel (for its own status), relayed to mainboard |
| **UART2 mainboard link** | UART, 8N1 | **115200** | vendor `0x41` read / `0x10` write | the mainboard |

The envelope is documented once in [frame-format.md](frame-format.md); the crypto in
[aes-encryption.md](aes-encryption.md). The function codes differ per link but the wrapping is
identical.

## The three control paths

### 1. Local BLE (the goal of this project)
A BLE client connects to the panel's `0xABF0` service and exchanges AES-wrapped Modbus. This is
what the MCZ app does at close range and what Home Assistant can do via a BlueZ host or an ESPHome
BLE proxy. No cloud, no stove modification. See
[panel/ble-control-protocol.md](../panel/ble-control-protocol.md).

### 2. Cloud MQTT (the default, documented for completeness)
The panel connects out to the MCZ broker over MQTT/TLS. This is the path the manufacturer uses; it
needs internet and the manufacturer's infrastructure. Documented in
[stove/cloud-mqtt.md](../stove/cloud-mqtt.md), but **not** the path this project relies on.

### 3. UART2 to the mainboard (internal)
Not a control path you use from outside — it's the internal link between the panel and the
combustion board. It matters here because a **bench** panel (an ESP32 running the panel firmware
with no real stove attached) will not fully come up until it sees a mainboard answering on UART2.
That is what the [emulator](../stove/emulator/README.md) provides. See
[stove/uart2-mainboard-link.md](../stove/uart2-mainboard-link.md).

## Why a bench emulator exists

The physical stove is not on hand during development. To build and validate the BLE client early,
the panel firmware is run on a spare ESP32. That bench panel behaves almost like a real one, except
that with **no mainboard on UART2** it keeps retrying the mainboard and treats itself as "not
ready." The mainboard emulator answers those UART2 requests so the panel behaves as if a stove is
attached — letting the whole local pipeline be tested without the appliance.
