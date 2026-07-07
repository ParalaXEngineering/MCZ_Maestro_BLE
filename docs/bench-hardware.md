# Bench hardware inventory

The physical rig used to develop against the stove before the real appliance is available. Two
ESP32-D0WD-V3 dev boards (both CP210x USB-serial), plus the development laptop's Bluetooth adapter.

| Board | Antenna | Chip MAC | BLE advertising address | Role |
|-------|---------|----------|-------------------------|------|
| Panel | **yes** | `a0:a3:b3:2c:f0:80` | **`A0:A3:B3:2C:F0:82`** | Runs the panel firmware; BLE server `MCZ_EP000000`, GATT `0xABF0`. With the antenna it scans at ~−45 dBm (vs −78…−98 without). |
| Emulator | no (BLE unused) | `ec:e3:34:21:19:90` | `EC:E3:34:21:19:92` | Runs MicroPython + the mainboard emulator on UART2. No BLE, so no antenna needed. |

Development laptop Bluetooth adapter MAC (what the panel logs as `MA …` on a connect):
**`9c:67:d6:0a:36:6e`**.

Notes:
- **Target the panel by its advertising address**, e.g.
  `python ble-client/mcz_ble_client.py dump --address A0:A3:B3:2C:F0:82`. COM port numbers are
  assigned by the OS and can change when boards are re-plugged; the advertising address is stable.
- The antenna matters: the panel board must have a U.FL/IPEX 2.4 GHz antenna attached or BLE is
  unreliable.
- The emulator board is wired to the panel's UART2 — see
  [../stove/emulator/README.md](../stove/emulator/README.md) for the pinout.

## Backups (nothing here is irreversible)

- `panel/firmware/com39_antenna_backup.bin` — the panel board's original 4 MB flash.
- `panel/firmware/used_flash_0x0.bin` — the full 7.4 MB dump (source of all the analysis).
- `panel/firmware/flash_4mb/` — the trimmed set to reflash panel firmware onto any ≥4 MB board.
- The emulator board can be returned to panel firmware from `flash_4mb/` at any time.

## NVS / advertising state (bench gotcha)

With the original NVS in place the panel finds the previous owner's stored BLE bond, logs
`Found RE 1`, and advertises *directed* to that phone (invisible to a general scan). After erasing
NVS it logs `Found RE 0` + `ADV start` (general, discoverable) and `Dev: -1 - 4354` (whitelist
count −1 = empty; `4354` = a constant build id). Erase with:

```
esptool --chip esp32 --port <PORT> erase-region 0x9000 0x4000
```

See [../panel/README.md](../panel/README.md) for the full boot sequence.
