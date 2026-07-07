# Stove side: mainboard, its link to the panel, and the cloud path

This folder covers everything *except* the panel board itself: the combustion **mainboard**, the
internal **UART2 link** between panel and mainboard, the **cloud/MQTT** path, and the bench
**emulator** that stands in for a real mainboard.

- The panel↔mainboard protocol → [uart2-mainboard-link.md](uart2-mainboard-link.md)
- The cloud path (documented for completeness) → [cloud-mqtt.md](cloud-mqtt.md)
- The bench mainboard emulator → [emulator/README.md](emulator/README.md)

## The combustion mainboard

The mainboard runs the stove: auger, combustion and flue fans, igniter, temperature sensors, and
safety logic. It holds the **live register state** and answers the panel as a **Modbus slave**. All
stove control — from the app, from the cloud, or from a local BLE client — ultimately becomes Modbus
register operations that the panel forwards to this board.

The physical mainboard is not on hand during development, so its role is played on the bench by the
[emulator](emulator/README.md). Once the real stove arrives, captures from the genuine mainboard
will fill the remaining gaps (notably the exact `0x41` read reply — see
[../docs/status-and-open-questions.md](../docs/status-and-open-questions.md)).

## Why this matters for the BLE goal

Even though the target is *local BLE control of the panel*, the mainboard cannot be ignored: without
something answering on UART2 the panel sits in an endless mainboard-timeout loop and never settles
into normal BLE operation. So a working bench — panel + something answering on UART2 — is a
prerequisite for exercising the BLE path without the physical appliance. That "something" is the
emulator. (Note: the panel's BLE **readiness gate** turned out *not* to be a mainboard-health check —
it is a commissioning/pairing gate that no UART reply opens; see
[../docs/ble-readiness-gate-RESOLVED.md](../docs/ble-readiness-gate-RESOLVED.md). The emulator is
still needed to stop the timeout loop and answer register reads.)
