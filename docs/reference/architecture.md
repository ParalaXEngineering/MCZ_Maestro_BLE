# System architecture (reference)

How an MCZ Maestro+ stove is wired internally, and the three ways it can be controlled. This
frames everything else: the crypto, the frames, and the register map all exist to talk to the
**panel**, which relays to the **mainboard**.

## The three boards

| Board | What it is | Interfaces |
|-------|------------|------------|
| **Combustion mainboard** | Runs the actual stove (auger, fans, igniter, safety). Holds the live register state. | Modbus **slave** on a UART |
| **Panel (HMI)** | ESP32 Wi-Fi/BLE controller with the touch display. Bridges cloud/BLE ⇄ mainboard. | Wi-Fi, BLE, Modbus **master** on UART2 |
| *(external)* Phone / HA / cloud | The controllers that drive the panel | BLE or MQTT |

The reference unit is an MCZ "RAY Comfort Air 8 XUP" Maestro+ (M2-series). Panel version string:
`M2S.AIR.24.20, Panel:16`.

## The panel is a relay, not the brain

All stove control is **Modbus register reads and writes** against the mainboard. The panel never
decides stove behaviour itself; it relays register operations from whichever controller is talking
to it:

```
                   ┌──────────────────────── PANEL (ESP32) ───────────────────────┐
  BLE client ────► │  BLE service 0xABF0  ─┐                                        │
  (HA / app)       │                        ├─► Modbus master ─► UART2 ─► mainboard │
  MQTT (cloud) ──► │  MQTT client           ─┘        (AES-wrapped Modbus)          │
                   └────────────────────────────────────────────────────────────────┘
```

Both the BLE service and the cloud client turn into the **same** Modbus traffic toward the
mainboard. That is why the [register map](../ble-protocol.md#register-map) is enough to control
everything.

## One envelope, two local links

The two local links use the **same** message envelope — AES-128-CBC over a Modbus PDU with a shared
token and a rolling counter. Only the function codes and transport differ:

| Link | Transport | Modbus function codes | Who answers |
|------|-----------|-----------------------|-------------|
| **BLE control** | GATT `0xABF0` (write `0xABF1`, notify `0xABF2`), MTU 517 | `0x03` read / `0x06` write | the panel, relayed to mainboard |
| **UART2 mainboard link** | UART, 115200 8N1 | vendor `0x41` read / `0x10` write | the mainboard |

The envelope and register map are specified in [ble-protocol.md](../ble-protocol.md); the UART2 link
in [uart2-link.md](uart2-link.md).

## The three control paths

1. **Local BLE — the goal.** A client connects to `0xABF0` and exchanges AES-wrapped Modbus, exactly
   as the MCZ app does at close range. No cloud, no stove modification. Reachable from Home Assistant
   via a BlueZ host or an ESPHome BLE proxy. See [ble-protocol.md](../ble-protocol.md).
2. **Cloud MQTT — the manufacturer default.** The panel connects out to the MCZ broker over MQTT/TLS.
   Needs internet and MCZ infrastructure; **not** used by this project. See [cloud-mqtt.md](cloud-mqtt.md).
3. **UART2 to the mainboard — internal.** Not an external control path; it's the panel↔mainboard
   link. It matters because a bench panel won't settle until something answers on UART2 (that's what
   the [emulator](../../stove/emulator/README.md) provides). See [uart2-link.md](uart2-link.md).

## Why a bench emulator exists

The physical stove isn't on hand during development, so the panel firmware runs on a spare ESP32.
With **no mainboard on UART2** the panel loops on mainboard timeouts and treats itself as "not
ready." The mainboard emulator answers those UART2 polls so the panel behaves as if a stove is
attached — letting the whole local pipeline be tested without the appliance.
