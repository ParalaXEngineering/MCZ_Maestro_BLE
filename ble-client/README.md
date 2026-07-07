# BLE client

`mcz_ble_client.py` is a pure-Python client for the panel's local BLE control service (`0xABF0`). It
implements the whole protocol core — AES framing, Modbus, the register map, and a status decoder —
and is the intended foundation for the eventual Home Assistant integration. It mirrors the community
project `foyewmaddeeb/mcz-maestro-ble`.

Protocol references: [../panel/ble-control-protocol.md](../panel/ble-control-protocol.md),
[../docs/frame-format.md](../docs/frame-format.md), [../docs/modbus-registers.md](../docs/modbus-registers.md).

## Requirements

```
pip install bleak cryptography          # (also in ../requirements.txt)
```

`bleak` provides cross-platform BLE (BlueZ on Linux, WinRT on Windows, CoreBluetooth on macOS).
Linux / Home Assistant is the eventual production host; it handles BLE bonding transparently and
supports ESPHome BLE proxies.

## Commands

```bash
python mcz_ble_client.py selftest                 # no hardware: build+encrypt+decrypt+verify a frame
python mcz_ble_client.py scan                      # list nearby MCZ_EP* devices
python mcz_ble_client.py dump   --address <MAC>    # connect + full GATT enumeration
python mcz_ble_client.py monitor                   # connect, subscribe 0xABF2, poll the status block
python mcz_ble_client.py repl                      # interactive: poll / read / write / settemp / setpower
python mcz_ble_client.py read  <reg> <count>
python mcz_ble_client.py write <reg> <value>
```

Useful flags: `--address <MAC>` to target a specific board, `--pair` to force pairing on Linux/BlueZ,
`--timeout <s>` for scan/connect.

`selftest` passing confirms the crypto/framing/Modbus/CRC are correct independent of any hardware —
that part was never the problem.

## Also here

- `ble_connect_test.py` — a minimal single-attempt connect that prints each step; handy for checking
  whether a connection reaches the panel and what the panel's readiness gate decides (watch the panel
  console in parallel).
