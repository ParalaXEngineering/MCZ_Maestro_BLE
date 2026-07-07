# Panel board (ESP32 Wi-Fi/BLE HMI)

The stove's connectivity/display controller — a classic ESP32 that bridges the outside world (cloud
MQTT, local BLE) to the combustion mainboard over UART2. This folder holds its firmware images, the
flashing set, and the disassembly tools. The prose about *what the panel does* lives in `docs/`:

- The local BLE control protocol it exposes → [../docs/ble-protocol.md](../docs/ble-protocol.md)
- Firmware reverse-engineering notes → [../docs/reference/firmware-disassembly.md](../docs/reference/firmware-disassembly.md)
- The internal UART2 link → [../docs/reference/uart2-link.md](../docs/reference/uart2-link.md)

## Hardware & firmware facts

| Item | Value |
|------|-------|
| SoC | ESP32-D0WD-V3 (Xtensa LX6, dual-core), rev v3.1 |
| Panel app | project `DM2.AIR`, app v16, ESP-IDF 5.2.1, wolfSSL, Bluedroid |
| Full version string | `M2S.AIR.24.20, Panel:16` (an M2-series stove) |
| Example unit | MCZ "RAY Comfort Air 8 XUP" Maestro+ |
| Flash | dump spans to `0x710000` → needs an **8 MB** board for the full image (a trimmed 4 MB set is provided) |
| Security | **no flash encryption, no secure boot** — the app is plaintext |

The panel advertises over BLE as `MCZ_EP<serial>` (`MCZ_EP000000` when NVS is wiped).

## Partition table (from the table at `0x8000`)

| Part | Offset | Size | Role |
|------|--------|------|------|
| nvs | `0x9000` | `0x4000` (16 K) | Wi-Fi creds, BLE bonds, calibration, config — plaintext |
| otadata | `0xd000` | `0x2000` | active OTA slot selector (ota_0 active) |
| phy_init | `0xf000` | `0x1000` | RF calibration |
| ota_0 | `0x10000` | `0x300000` | app v16 (active) |
| ota_1 | `0x310000` | `0x300000` | app v14 (previous) |
| storage | `0x610000` | `0x100000` | SPIFFS |

## Boot behaviour on the bench (serial @ 115200)

Running the panel firmware on a bare ESP32 (no display, no mainboard):

1. Boots the v16 app, then loops `Timeout N` — repeatedly trying to reach the absent mainboard on
   UART2. Harmless, and runs in parallel with BLE.
2. After the init retries expire (~10–15 s): `Controller enable → Bluedroid enable → Gatt cb → Gap cb
   → App reg → ADV start`.
3. **Advertising gotcha:** with the original NVS in place the panel finds the previous owner's stored
   BLE bond and advertises *directed* to that phone only — a new scanner never sees it. Wipe NVS for
   general discoverable advertising:
   ```
   esptool --chip esp32 --port <PORT> erase-region 0x9000 0x4000
   ```
   (This mirrors a real stove: an already-paired stove advertises only to its phone until you press
   **+ and −** together.) After wiping it advertises as `MCZ_EP000000` and logs `Dev: -1 - 4354`
   (whitelist empty; `4354` = a constant build id).
4. `timerPairBle` means advertising is a **timed** pairing window (~5 min); reset the board to reopen.

## Files here

| Path | What |
|------|------|
| `firmware/used_flash_0x0.bin` | Full 7.4 MB raw flash dump (bootloader + both apps + NVS + SPIFFS) |
| `firmware/com39_antenna_backup.bin` | 4 MB backup of the bench panel board's original flash |
| `firmware/flash_4mb/` | Trimmed 4 MB flash set (boots the panel on any ≥4 MB board) + its own README |
| `firmware/mcz_broker_ca_digicert.pem` | The DigiCert CA the panel pins for cloud MQTT/HTTPS |
| `tools/xdis.py` | Robust Xtensa disassembler / xref helper (see the disassembly notes) |
| `tools/analyze.py` | Capstone-based disassembler / xref helper (older; desyncs on this image) |
| `tools/patch_open_gate.py` | Builds the bench-only gate-open app image |
| `tools/serial_watch.py` / `console_watch.py` | Capture a board's console @115200 (with / without reset) |
| `tools/win_diag.py`, `tools/win_pair.py` | Windows BLE connect/pair diagnostics (reference) |

## Flashing

Exact commands are in [`firmware/flash_4mb/README.md`](firmware/flash_4mb/README.md); the end-to-end
bench recipe is in [`../docs/setup.md`](../docs/setup.md). In short, for a ≥4 MB board:

```
esptool --chip esp32 --port <PORT> --baud 460800 \
  write-flash --flash_mode dio --flash_freq 40m --flash_size detect \
  0x1000  firmware/flash_4mb/bootloader.bin \
  0x8000  firmware/flash_4mb/partitions_4mb.bin \
  0x9000  firmware/flash_4mb/nvs.bin \
  0xd000  firmware/flash_4mb/otadata_erased.bin \
  0xf000  firmware/flash_4mb/phy_init.bin \
  0x10000 firmware/flash_4mb/app_ota0.bin
```

On an 8/16 MB board you can instead flash the whole image: `write-flash 0x0 firmware/used_flash_0x0.bin`.

> **Antenna:** a WROOM-32**U** has no onboard antenna — attach a U.FL/IPEX 2.4 GHz antenna or BLE is
> effectively unusable (−45 dBm with antenna vs −78…−98 without). Back up a board before flashing.
