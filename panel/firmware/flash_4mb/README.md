# 4 MB flash set (for ESP32-WROOM-32U and other 4 MB boards)

The full `used_flash_0x0.bin` needs 8 MB. This set trims the image to fit **4 MB** by keeping
only what's needed to boot and run the BLE panel firmware:

| offset   | file                | what |
|----------|---------------------|------|
| 0x1000   | bootloader.bin      | 2nd-stage bootloader (from dump) |
| 0x8000   | partitions_4mb.bin  | **custom** table: nvs, otadata, phy, ota_0, storage — ends at 4 MB |
| 0x9000   | nvs.bin             | original NVS (calibration/config) |
| 0xd000   | otadata_erased.bin  | erased → bootloader boots ota_0 |
| 0xf000   | phy_init.bin        | RF calibration |
| 0x10000  | app_ota0.bin        | **active app, version 16** (the running firmware) |

Dropped vs. the original: `ota_1` (older v14 backup) and the 1 MB `storage` is shrunk to
0xF0000. Neither is needed to bring up BLE. Works on any board **≥ 4 MB** (on an 8/16 MB board
it just leaves the rest empty).

## 0. First, confirm your flash size
```
esptool --port /dev/tty.usbserial-XXXX flash_id
```
- Reports **4MB** → use this set (below).
- Reports **8MB/16MB** → you *may* instead flash the original whole dump:
  `esptool ... write_flash 0x0 ../used_flash_0x0.bin` (more faithful). This 4 MB set also works.

## 1. Back up the board, then flash
```
esptool --chip esp32 --port /dev/tty.usbserial-XXXX --baud 921600 read_flash 0x0 0x400000 devboard_backup.bin
esptool --chip esp32 --port /dev/tty.usbserial-XXXX erase_flash

esptool --chip esp32 --port /dev/tty.usbserial-XXXX --baud 921600 \
  write_flash --flash_mode dio --flash_freq 40m --flash_size detect \
  0x1000  bootloader.bin \
  0x8000  partitions_4mb.bin \
  0x9000  nvs.bin \
  0xd000  otadata_erased.bin \
  0xf000  phy_init.bin \
  0x10000 app_ota0.bin
```
`--flash_size detect` auto-patches the bootloader header to your real chip size.

## 1b. (Optional) Gate-open build — to actually TEST BLE control on the bench

The stock app refuses every BLE control session with `rejected Nm0` until the panel's
commissioning/pairing flow sets an internal enable bit — which never happens on a bare dev
board (full analysis: [../../../docs/ble-readiness-gate-RESOLVED.md](../../../docs/ble-readiness-gate-RESOLVED.md)).
To validate the BLE stack end-to-end on the bench, flash a patched app that jumps past both
readiness gates straight into the whitelist logic (empty whitelist → auto-register + accept).

Build the patched image (reproducible; recomputes the esp-image checksum + SHA-256 so the
bootloader accepts it):

```
python ../../tools/patch_open_gate.py app_ota0.bin app_ota0_gateopen.bin
```

Flash **only the app** over an already-flashed board, and clear NVS so the whitelist is empty:

```
esptool --chip esp32 --port <PORT> --baud 921600 write_flash 0x10000 app_ota0_gateopen.bin
esptool --chip esp32 --port <PORT> erase-region 0x9000 0x4000
```

(Or do a full flash as in step 1, substituting `app_ota0_gateopen.bin` for `app_ota0.bin`.)

The patch changes exactly 3 instruction bytes at vaddr `0x400d26bd`
(`l8ui a8,[state+0x54]` → `j 0x400d26cf`) plus the image's checksum/SHA. It is **bench
validation only** — it does not tell you how an unmodified panel opens the gate (that's
commissioning; see the RESOLVED doc). Revert by reflashing `app_ota0.bin`.

> **Validated on hardware (2026-07-07).** This image was flashed and driven end-to-end: it
> boots cleanly to `ADV start`, a BLE connect is **accepted** (no `rejected Nm0`), and
> encrypted `0xABF0` register reads + a write round-trip to the mainboard emulator and back.
> Evidence: `captures/gateopen_panel_console.log`, `captures/gateopen_ble_session.log`,
> `captures/gateopen_emulator.log`. Full write-up:
> [../../../docs/ble-readiness-gate-RESOLVED.md](../../../docs/ble-readiness-gate-RESOLVED.md#bench-validation-done-2026-07-07).

### Test it

1. Run the **mainboard emulator** on the second board (so register READS get answered) —
   see [../../../stove/emulator/README.md](../../../stove/emulator/README.md).
2. Watch the panel console on connect: it should now log the whitelist/accept path
   (e.g. `Found Pair` / auto-register) instead of `rejected Nm0`.
3. From the laptop:
   ```
   python ../../../ble-client/mcz_ble_client.py scan                     # find MCZ_EP*
   python ../../../ble-client/mcz_ble_client.py dump    --address <MAC>  # GATT enumeration
   python ../../../ble-client/mcz_ble_client.py read  0x02BC 1 --address <MAC>   # a register read
   python ../../../ble-client/mcz_ble_client.py write 0x03F7 210 --address <MAC> # set temp 21.0C
   ```
   On Linux/BlueZ add `--pair`. `read` values come from the emulator's register map.

## 2. Watch it boot (115200 serial)
Look for `Bluedroid enable` / `ADV start` / `hdl_bleServer_init` and the `GATTS DATABASE DUMP`.
Then run `python ../../../ble-client/mcz_ble_client.py scan` from your laptop — you should see `MCZ_EP`.

## Notes / risks
- **Antenna:** WROOM-32U has NO onboard antenna — attach a U.FL/IPEX 2.4 GHz antenna or BLE won't
  work.
- First boot formats the (erased) `storage` spiffs — normal, may add a second or two.
- Single app slot is fine for the bench (OTA isn't used). If it bootloops before `ADV start`,
  copy the last serial lines — that tells us which init blocks without the real panel hardware,
  and we adjust.
- Reminder: with no mainboard on UART2, register READS won't be answered; this validates BLE +
  pairing + service 0xABF0 + frame acceptance (see ../../ble-control-protocol.md). For real register
  values, run the mainboard emulator too (see ../../../stove/emulator/README.md).

> This file documents the trimmed 4 MB flash set specifically. For the canonical panel overview and
> flashing walkthrough, see [../../README.md](../../README.md).
