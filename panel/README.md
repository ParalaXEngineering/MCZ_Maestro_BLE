# Panel board (ESP32 Wi-Fi/BLE HMI)

The panel is the stove's connectivity/display controller. It is a classic ESP32 that bridges the
outside world (cloud MQTT, local BLE) to the combustion mainboard over UART2. Everything in this
folder is about that board: its firmware, the local BLE protocol it exposes, the reverse-engineering
notes, the flash images, and the serial/analysis tools.

- Local BLE control protocol → [ble-control-protocol.md](ble-control-protocol.md)
- Firmware reverse-engineering notes → [disassembly-notes.md](disassembly-notes.md)
- The AES/frame/register specs it shares with the mainboard link → [`../docs/`](../docs/)

## Hardware & firmware facts

| Item | Value |
|------|-------|
| SoC | ESP32-D0WD-V3 (classic Xtensa LX6, dual-core), rev v3.1 |
| Panel app | project `DM2.AIR`, app version 16, ESP-IDF 5.2.1, wolfSSL, Bluedroid |
| Full version string | `M2S.AIR.24.20, Panel:16` (an M2-series stove) |
| Example unit | MCZ "RAY Comfort Air 8 XUP" Maestro+ |
| Flash | dump spans to `0x710000` → needs an **8 MB** board for the full image (a trimmed 4 MB set is also provided) |
| Security | **no flash encryption, no secure boot** — the app is plaintext |

The panel advertises over BLE as `MCZ_EP<serial>` (e.g. `MCZ_EP000000` when NVS is wiped).

## Partition table (from the table at `0x8000`)

| Part | Offset | Size | Role |
|------|--------|------|------|
| nvs | `0x9000` | `0x4000` (16 K) | Wi-Fi creds, BLE bonds, calibration, config — plaintext |
| otadata | `0xd000` | `0x2000` | active OTA slot selector (ota_0 is active) |
| phy_init | `0xf000` | `0x1000` | RF calibration |
| ota_0 | `0x10000` | `0x300000` | app v16 (active) |
| ota_1 | `0x310000` | `0x300000` | app v14 (previous) |
| storage | `0x610000` | `0x100000` | SPIFFS |

## Boot behaviour on the bench (serial @ 115200)

Running the panel firmware on a bare ESP32 (no display, no mainboard):

1. Boots the v16 app, then loops `Timeout N` — the panel repeatedly trying to reach the absent
   mainboard on UART2. This loop is harmless and runs in parallel with BLE.
2. After the init retries expire (~10–15 s) it continues: `Controller enable → Bluedroid enable →
   Gatt cb → Gap cb → App reg → ADV start`.
3. **Advertising gotcha:** with the original NVS in place, the panel finds the previous owner's
   stored BLE bond and advertises *directed* to that phone only — a new scanner never sees it. Wipe
   NVS to get general discoverable advertising:
   ```
   esptool --chip esp32 --port <PORT> erase-region 0x9000 0x4000
   ```
   (This mirrors a real stove: an already-paired stove only advertises to its phone until you press
   **+ and −** together to re-enter pairing mode.) After wiping it advertises as `MCZ_EP000000`, and
   the boot log shows `Dev: -1 - 4354` (whitelist count −1 = empty; `4354` = a constant build id).
4. `timerPairBle` means advertising is a **timed** pairing window (~5 min); reset the board (EN
   button / re-plug) to reopen it.

## Files here

| Path | What |
|------|------|
| `firmware/used_flash_0x0.bin` | The full 7.4 MB raw flash dump of the panel (bootloader + both apps + NVS + SPIFFS) |
| `firmware/com39_antenna_backup.bin` | 4 MB backup of the bench panel board's original flash |
| `firmware/flash_4mb/` | Trimmed 4 MB flash set (boots the panel on any ≥4 MB board) + its own README |
| `firmware/mcz_broker_ca_digicert.pem` | The DigiCert CA the panel pins for cloud MQTT/HTTPS |
| `tools/analyze.py` | Xtensa disassembler / xref helper for the dump (see disassembly-notes.md) |
| `tools/serial_watch.py` | Capture a board's console @115200, optionally resetting it first |
| `tools/console_watch.py` | Capture a console @115200 **without** resetting the board |
| `tools/win_diag.py`, `tools/win_pair.py` | Windows BLE connect/pair diagnostics (reference) |

## Flashing the panel firmware to a bench board

Full instructions are in `firmware/flash_4mb/README.md`. In short, for an ESP32 with ≥4 MB flash:

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

On an 8/16 MB board you can instead flash the faithful whole image:
`esptool ... write-flash 0x0 firmware/used_flash_0x0.bin`.

> **Antenna:** a WROOM-32**U** has no onboard antenna — attach a U.FL/IPEX 2.4 GHz antenna or BLE is
> effectively unusable (bench comparison: −45 dBm with antenna vs −78…−98 without).

Back up a board before flashing, and you can always restore it later
(`esptool ... write-flash 0x0 <backup>.bin`).
