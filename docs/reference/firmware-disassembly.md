# Firmware disassembly notes (reference)

Reverse-engineering reference for the panel firmware image — where the protocol constants, the
readiness-gate logic, and the UART2 configuration were recovered from. Written so the work can be
continued: image layout, tooling, and every load-bearing address. Everything comes from static
analysis of [`panel/firmware/used_flash_0x0.bin`](../../panel/firmware/); no stove firmware is
modified.

## Image layout

App project `DM2.AIR`, app v16, ESP-IDF 5.2.1. App starts at flash `0x10000`. Segment map (for
translating virtual address ↔ file offset):

| Segment | Virtual addr | Length | File offset (abs) | Contents |
|---------|-------------|--------|-------------------|----------|
| DROM | `0x3f400020` | `0x1992a4` | `0x10020` | read-only data / strings |
| IROM | `0x400d0020` | `0x11202c` | `0x1b0020` | flash code |
| IRAM | `0x40080000` | `0x1fad8` | `0x2c3f4c` | IRAM code |

App entry point: `0x40083ab0`.

## Tooling

Two disassemblers live in [`panel/tools/`](../../panel/tools/); both read
`../firmware/used_flash_0x0.bin` and need `capstone>=6.0` (`pip install --pre capstone`).

- **`analyze.py`** — Capstone-based helper. Commands: `xref <addr>`, `dis <start> <end>`,
  `disaround <addr> <back> <fwd>`. **Caveat:** Capstone's Xtensa decoder desyncs on this image (emits
  spurious `ee.*` vector ops, loses alignment). String/global `xref` is reliable; long linear
  disassembly is not.
- **`xdis.py`** (more robust — this resolved the readiness gate) — steps by the Xtensa
  instruction-length rule (16-bit iff `byte0 & 0x0f` in `{8,9,C,D}`, else 24-bit) so it never trusts
  Capstone's stream for alignment, flags `ee.*` garbage as a desync marker, brute-forces the start
  offset so a target lands on a boundary, and does deterministic `l32r`/`CALL` xref scans. Commands:
  `dis <start> <end>`, `at <target> [back] [fwd]`, `bytes <addr> <n>`, `xref <addr>`.

## Protocol constants (located in the image)

| Name | Value | File offset |
|------|-------|-------------|
| `TOKEN` | `31dd34512639377b05a2510de725fc75` | `0x6ce86` |
| `KEY1` | `6e296b0bbb1d43f36e47f72e7b6f2e77` | `0x6ce96` (copy in ota_1 at `0x354ad2`) |
| `IV0` | `da1a557349f25c641b1a368af5b218a7` | `0x1041c` |

These sit in read-only data next to the `0xABF0/1/2` attribute table. See
[ble-protocol.md](../ble-protocol.md#the-message-envelope).

## The BLE connect handler and readiness gate

Handler at **`0x400d26ae`** (prints `Connect`). Works with `0x3ffcd224` (main state struct, referenced
from ~280 places) and `0x3ffc6afa` (the BLE whitelist: `[count:int8][ up to 19 × 6-byte MAC ]`,
entries at offset +1).

```
GATE 1 @ 0x400d26c0 : if ([0x3ffcd224 + 0x54] bit1) == 0  -> reject
GATE 2 @ 0x400d26c9 : if ([0x3ffcd224 + 0x52] bit2) != 0  -> reject
then whitelist @ 0x3ffc6afa:
    count == -1 (empty) -> auto-register connecting MAC + accept   (first-pairing path)
    count >=  0         -> match MAC: match -> "Found Pair" @0x400d2b78
                                       miss  -> "rejected Nm0" @0x400d2bb6
```

The blocker on the bench is **GATE 1** (enable bit `[+0x54]` bit1 not set); GATE 2 is already clear
on a fresh, unbonded bench. "Ready" is a **commissioning/pairing** state, not a mainboard-comms
outcome — full analysis and the four callers of the enable-bit set site in
[readiness-gate.md](readiness-gate.md).

Related addresses:

- **Gate enable-bit SET:** `0x400d2d77` (`or a8,a8,2 ; s8i a8,[0x3ffcd224+0x54]`), fn `0x400d2d54`.
- **Gate enable-bit CLEAR helper:** `0x400d246e`.
- **GATE 2 fault-bit CLEAR:** `0x400eb46c`. **SET:** `0x400d2a18` (BLE-bond path). **Init to 0:** `0x400ec227`.
- **Shared reject target:** `0x400d2ab8` → `rejected Nm0`.
- **Whitelist add:** ~`0x400d25f2`. **Reset to −1:** `0x400d2c73`, `0x400d2dca`. NVS blob key
  `"whitelist"` (`0x3f40014a`), loaded at boot into `0x3ffc6afa`.
- **MAC match loop:** `0x400d2b3c`..`0x400d2bb9`.
- **BLE bringup:** `0x400d2eb5` (`timerPairBle` → Controller/Bluedroid → Gatt/Gap cb → App reg → ADV
  start). Pairing-window timer period `0x493e0` (= 300000 ms = 5 min).

## UART2 (panel ↔ mainboard) configuration

Init at **`0x400e9c44`**, guarded by `bnei a2, 2` (runs only for `UART_NUM_2`). The `uart_config_t`:

```
baud field = 0xe1 << 12 = 0xE1000     (pre-divide; effective line rate is that ÷8 = 115200)
data_bits  = 3  (UART_DATA_8_BITS)
parity     = 0  (none)
stop_bits  = 1
flow control off, default source clock
uart_set_pin(UART_NUM_2, 4, 5, -1, -1) -> TX = GPIO4, RX = GPIO5
```

Effective config: **115200 8N1**, TX = GPIO4, RX = GPIO5. The baud-field-vs-wire discrepancy is
explained (and measured) in [uart2-link.md](uart2-link.md).

## Response-parser error oracle

The panel narrates why it rejects a mainboard reply — extremely useful when tuning an emulated
mainboard:

| String | Referenced from | Meaning |
|--------|-----------------|---------|
| `Timeout %d` | — | no reply received on UART2 |
| `No x16 - %d` | `0x400d3980` | reply length not a multiple of 16 |
| `CRC Err` | `0x400d36a4` | Modbus CRC did not validate |
| `OtherAddress` | — | wrong slave address in the reply |
| `Incomplete Message` | `0x400d36e5` | reply shorter than expected |
| `Function Error` | `0x400d3717` | unexpected function code |
| `Exeption: %d` | — | reply was a Modbus exception |
| `Errata Message`, `Errata TRANS` | — | other malformed-reply paths |

The parser routes a reply through a validator (called from ~`0x400d3645`). On success it stores the
register data and updates state in `0x3ffcd224` (error counters at offsets `0x60` / `0x62`).

## Cloud (MQTT) client config

Built at `0x400d5049` (`esp_mqtt_client_config_t`). Values in [cloud-mqtt.md](cloud-mqtt.md); the
pinned CA is saved as `panel/firmware/mcz_broker_ca_digicert.pem`.

## Other useful symbols / strings

- Modbus helpers: `modbus_read`, `modbus_write`, `modbus_Mqtt_read` (the panel is the Modbus master).
- **BLE text-provisioning parser** (separate from `0xABF0`): field separator `0xB4`, scanf pattern
  `%[^=]=%[^\xB4]\xB4%s`. Commands: `SCAN=`, `CREDENTIALS=<ssid>\xB4<password>`, `CONNECT`
  (→ `CONNECTION_OK` / `ERR%03d`), `STATUS` (→ `CONNECTED:<ip>` / `UNCONNECTED`), `UNCONNECT`,
  `POTA=START` (panel OTA), `BOTA=START` (board OTA). Wi-Fi provisioning + firmware-update only,
  **not** stove control.
- Local network surfaces: a `tcp_server` socket used only to push firmware during POTA/BOTA. There is
  **no** local HTTP/WebSocket server; the only local control surface is `0xABF0`.
- Console strings: `Connect`, `MA %02x:…`, `rejected Nm0`, `Found Pair`, `Already saved`, `ADV start`,
  `disconnected`, `Dev: %d - %d`, `Timeout %d`, `Letto resetParam %d`.
