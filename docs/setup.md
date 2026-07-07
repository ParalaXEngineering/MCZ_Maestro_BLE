# Setup — building the bench

How to reproduce the two-board bench that stands in for a real stove: one ESP32 running the panel
firmware, a second running a mainboard emulator, wired together on UART2, driven from a laptop over
BLE. This is what let the BLE control stack be validated before the physical appliance was available.

```
  Laptop (BLE client) ──BLE──►  [ Panel board ]  ──UART2──►  [ Emulator board ]
                                 ESP32 + panel fw            ESP32 + MicroPython
                                 BLE server 0xABF0           answers Modbus polls
```

## What you need

- **2× ESP32 dev boards** (the reference bench used ESP32-D0WD-V3, both CP210x USB-serial).
- **A 2.4 GHz antenna** on the panel board. This matters: with a U.FL/IPEX antenna the panel scans at
  ~−45 dBm; without one, −78…−98 dBm and BLE is unreliable. A WROOM-32**U** has no onboard antenna.
- **A few jumper wires** for the UART2 link, kept short with a solid common ground.
- **Python** on the laptop: `pip install -r requirements.txt` (bleak, cryptography, pyserial, esptool).

### Board inventory (reference bench)

| Board | Antenna | Chip MAC | BLE advertising address | Role |
|-------|---------|----------|-------------------------|------|
| Panel | **yes** | `a0:a3:b3:2c:f0:80` | **`A0:A3:B3:2C:F0:82`** | Panel firmware; BLE server `MCZ_EP000000`, GATT `0xABF0` |
| Emulator | no | `ec:e3:34:21:19:90` | `EC:E3:34:21:19:92` | MicroPython + mainboard emulator on UART2 (BLE unused) |

Laptop Bluetooth adapter (what the panel logs as `MA …` on connect): `9c:67:d6:0a:36:6e`.

> **Target the panel by its advertising address**, not its COM port — COM numbers change when boards
> are re-plugged; the advertising address is stable. E.g.
> `python ble-client/mcz_ble_client.py dump --address A0:A3:B3:2C:F0:82`.

## Step 1 — Flash the panel firmware

Full instructions and exact esptool commands:
[`panel/firmware/flash_4mb/README.md`](../panel/firmware/flash_4mb/README.md). In short, for a ≥4 MB
board: back it up, then flash the trimmed 4 MB set (bootloader, partitions, nvs, otadata, phy, app).
On an 8/16 MB board you can instead flash the faithful whole image
(`write_flash 0x0 panel/firmware/used_flash_0x0.bin`). Board and partition facts:
[`panel/README.md`](../panel/README.md).

**NVS / advertising gotcha:** with the original NVS in place the panel finds the previous owner's
stored BLE bond, logs `Found RE 1`, and advertises *directed* to that phone (invisible to a general
scan). Erase NVS to get general, discoverable advertising (`Found RE 0` + `ADV start`, and
`Dev: -1 - 4354` = empty whitelist):

```
esptool --chip esp32 --port <PANEL_PORT> erase-region 0x9000 0x4000
```

## Step 2 — Flash and run the mainboard emulator

On the second board, flash MicroPython and deploy the emulator script. Full steps and wiring:
[`stove/emulator/README.md`](../stove/emulator/README.md). In short:

```bash
python -m esptool --chip esp32 --port <EMU_PORT> --baud 460800 \
    write-flash --erase-all 0x1000 stove/emulator/micropython_esp32.bin
python -m mpremote connect <EMU_PORT> fs cp stove/emulator/emulator_main.py :main.py
python -m mpremote connect <EMU_PORT> reset
```

The emulator opens UART2 at 115200 8N1, decrypts each of the panel's polls, checks the token, and
replies in the same AES envelope. With it running, the panel stops its mainboard-timeout loop.

## Step 3 — Wire the UART2 link

Two ESP32s, UART2-to-UART2, 3.3 V logic, common ground (no RS-485 transceiver needed):

```
  Panel GPIO4 (TX2) ───────►  Emulator GPIO5 (RX2)
  Panel GPIO5 (RX2) ◄───────  Emulator GPIO4 (TX2)
  Panel GND         ────────  Emulator GND
```

Keep the wires short and the ground solid. GPIO5 is a strapping pin — power the panel first (or keep
the emulator's TX from driving it low during panel boot). Details:
[reference/uart2-link.md](reference/uart2-link.md).

## Step 4 — Drive it from the laptop

```bash
python ble-client/mcz_ble_client.py selftest                       # no hardware: crypto round-trip
python ble-client/mcz_ble_client.py scan                            # find MCZ_EP* devices
python ble-client/mcz_ble_client.py dump    --address <PANEL_ADDR>  # full GATT enumeration
python ble-client/mcz_ble_client.py read  0x02BC 1 --address <PANEL_ADDR>
python ble-client/mcz_ble_client.py write 0x03F7 210 --address <PANEL_ADDR>   # set 21.0 °C
```

On Linux/BlueZ add `--pair`. Read values come from the emulator's placeholder register map, not a
real stove. More commands: [`ble-client/README.md`](../ble-client/README.md).

## Opening the readiness gate

A **stock** panel refuses every control session with `rejected Nm0` until its commissioning/pairing
flow sets an internal enable bit — which never happens on a bare dev board. Two ways forward:

- **On the bench, to validate the BLE stack now:** flash the **gate-open build** that bypasses both
  gate checks. Procedure:
  [`panel/firmware/flash_4mb/README.md`](../panel/firmware/flash_4mb/README.md#1b-optional-gate-open-build--to-actually-test-ble-control-on-the-bench).
  This is how the end-to-end validation was done (connect accepted, reads and a write round-tripped).
- **On a real stove:** enter pairing mode (press **+ and −** together), then the empty whitelist
  auto-accepts the first client — no patch needed.

Full explanation of the gate and why the mainboard can't open it:
[reference/readiness-gate.md](reference/readiness-gate.md).

## Backups (nothing here is irreversible)

- `panel/firmware/com39_antenna_backup.bin` — the panel board's original 4 MB flash.
- `panel/firmware/used_flash_0x0.bin` — the full 7.4 MB dump (source of all the analysis).
- `panel/firmware/flash_4mb/` — the trimmed set to reflash panel firmware onto any ≥4 MB board.
- The emulator board can be returned to panel firmware from `flash_4mb/` at any time. Revert a
  gate-open panel with `write_flash 0x10000 app_ota0.bin`.
