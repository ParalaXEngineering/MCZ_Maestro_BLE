# Firmware disassembly notes

Reverse-engineering reference for the panel firmware image. This is where the protocol constants,
the readiness-gate logic, and the UART2 configuration were recovered from. Written so the work can
be continued: it lists the image layout, the tooling, and every load-bearing address found.

Everything here comes from static analysis of `firmware/used_flash_0x0.bin` (the panel's own flash
image). No stove firmware is modified.

## Image layout

- App project `DM2.AIR`, app v16, ESP-IDF 5.2.1. App starts at flash `0x10000`.
- Segment map (parsed from the image header) for translating virtual address ↔ file offset:

| Segment | Virtual addr | Length | File offset (abs) | Contents |
|---------|-------------|--------|-------------------|----------|
| DROM | `0x3f400020` | `0x1992a4` | `0x10020` | read-only data / strings |
| IROM | `0x400d0020` | `0x11202c` | `0x1b0020` | flash code |
| IRAM | `0x40080000` | `0x1fad8` | `0x2c3f4c` | IRAM code |

App entry point (from the image header): `0x40083ab0`.

## Tooling: `tools/analyze.py`

A small helper built around Capstone's Xtensa backend (needs `capstone >= 6.0`; `pip install --pre
capstone`). It reads the image from `../firmware/used_flash_0x0.bin`. Commands:

```
python tools/analyze.py xref 0x3f4003e4          # find l32r references to an address (string/global)
python tools/analyze.py dis 0x400d26ae 0x400d2820 # disassemble a range
python tools/analyze.py disaround 0x400d2d77 0x80 0x60  # best-effort aligned disasm around an addr
```

> **Caveat:** the Capstone Xtensa decoder is imperfect and desyncs on this image (it emits spurious
> `ee.*` vector ops and loses instruction alignment). Cross-check by trying several start offsets,
> and treat single-instruction results with suspicion. String/global cross-references (`xref`) are
> reliable; long linear disassembly is not.

### Tooling: `tools/xdis.py` (more robust)

A companion that works around the desync: it steps by the Xtensa instruction-length rule (16-bit iff
`byte0 & 0x0f` in `{8,9,C,D}`, else 24-bit) so it never trusts capstone's stream for alignment, uses
capstone only to render one correctly-sized instruction, flags `ee.*`/vector garbage as a desync
marker, and can brute-force the start offset so a target address lands on a boundary. It also does
deterministic `l32r`/`CALL` xref scans. Commands: `dis <start> <end>`, `at <target> [back] [fwd]`,
`bytes <addr> <n>`, `xref <addr>`. Needs `capstone>=6.0` (`pip install --pre capstone`). This is what
resolved the readiness gate below.

## Protocol constants (located in the image)

| Name | Value | File offset |
|------|-------|-------------|
| `TOKEN` | `31dd34512639377b05a2510de725fc75` | `0x6ce86` |
| `KEY1` | `6e296b0bbb1d43f36e47f72e7b6f2e77` | `0x6ce96` (copy in ota_1 at `0x354ad2`) |
| `IV0` | `da1a557349f25c641b1a368af5b218a7` | `0x1041c` |

These sit in read-only data next to the `0xABF0/1/2` attribute table. See
[../docs/aes-encryption.md](../docs/aes-encryption.md).

## The BLE connect handler and readiness gate

Handler at **`0x400d26ae`** (prints `Connect`). It works with:

- `0x3ffcd224` — the panel's main state struct (referenced from ~280 places).
- `0x3ffc6afa` — the BLE whitelist: `[count:int8][ up to 19 entries × 6-byte MAC ]`, entries start
  at offset +1.

Decision flow:

```
GATE 1 @ 0x400d26c0 : if ([0x3ffcd224 + 0x54] bit1) == 0  -> reject
GATE 2 @ 0x400d26c9 : if ([0x3ffcd224 + 0x52] bit2) != 0  -> reject
then the whitelist @ 0x3ffc6afa:
    count == -1 (empty) -> auto-register the connecting MAC + accept   (first-pairing path)
    count >=  0         -> match MAC: match -> "Found Pair" @0x400d2b78
                                       miss  -> "rejected Nm0" @0x400d2bb6
```

The boot log line `Dev: -1 - 4354` shows the whitelist is empty (`-1`), so the whitelist would
auto-accept. The blocker on the bench is **GATE 1** — the enable bit `[+0x54]` bit1 is not set.
GATE 2 (`[+0x52]` bit2) is already clear on a fresh, unbonded bench.

**RESOLVED (2026-07-07):** "ready" is a **commissioning/pairing** state, not a mainboard-comms
outcome. The enable-bit set at `0x400d2d77` (function entry `0x400d2d54`) has exactly four callers,
and all are provisioning/pairing/UI paths — none is the mainboard poll:

| Caller | Path |
|--------|------|
| `0x400d2fe0` (fn `0x400d2fd4`) | BLE task start; guard `bnez a2` skips enable unless arg==0, but the sole caller `0x400e9346` passes `a10=1` → never enables |
| `0x400d828e` (fn `0x400d80bc`) | panel UI/pairing state machine (dispatch on `0x3ffc67a0`) |
| `0x400eab55` | `Got credentials` Wi-Fi provisioning (`RST_PARAM` NVS, `[+0x61]` pre-gate) |
| `0x400eada9` (fn `0x400eaae8`) | `Menu resetParam` pairing/reset menu (dispatch table `0x400ebff8`) |

GATE 2's bit2 is set only by the BLE-bond path (`0x400d2a18`, after `Already saved`) and cleared at
init (`0x400ec227`) / in the supervisor (`0x400eb46c`); a UART timeout or a successful reply never
sets it. No mainboard register is compared to drive either gate. Full writeup:
[../docs/ble-readiness-gate-RESOLVED.md](../docs/ble-readiness-gate-RESOLVED.md).

Related addresses:
- **Gate enable-bit SET:** `0x400d2d77` (`or a8,a8,2 ; s8i a8,[0x3ffcd224+0x54]`), fn `0x400d2d54`.
- **Gate enable-bit CLEAR helper:** `0x400d246e`.
- **GATE 2 fault-bit CLEAR:** `0x400eb46c` (`movi.n a9,-5 ; and ; s16i [+0x52]`). **SET:** `0x400d2a18`
  (BLE-bond path). **Init to 0:** `0x400ec227`.
- **Shared reject target:** `0x400d2ab8` (both gate failures jump here → `rejected Nm0`).
- **Whitelist add:** ~`0x400d25f2` (count = min(count+1, 19); copy 6-byte MAC to base+1+6·idx).
- **Whitelist reset to −1:** `0x400d2c73` and `0x400d2dca`. NVS blob key `"whitelist"` (`0x3f40014a`),
  loaded at boot into `0x3ffc6afa`.
- **MAC match loop:** `0x400d2b3c`..`0x400d2bb9`.
- **BLE bringup:** `0x400d2eb5` (`timerPairBle` → Controller init/enable → Bluedroid → Gatt/Gap cb →
  App reg → ADV start). Pairing-window timer period `0x493e0` (= 300000 ms = 5 min).

## UART2 (panel ↔ mainboard) configuration

Init function at **`0x400e9c44`**, guarded by `bnei a2, 2` (runs only for `UART_NUM_2`). The
`uart_config_t` it builds:

```
movi a8, 0xe1 ; slli a8, a8, 0xc ; s32i a1,0    -> baud field = 0xe1 << 12 = 0xE1000
movi a8, 3                        ; s32i a1,4    -> data_bits = 3  (UART_DATA_8_BITS)
movi a8, 0                        ; s32i a1,8    -> parity    = 0  (none)
movi a8, 1                        ; s32i a1,0xc  -> stop_bits = 1
(offsets 0x10/0x14/0x18 zeroed    -> flow control off, default source clock)
uart_set_pin(UART_NUM_2, 4, 5, -1, -1)          -> TX = GPIO4, RX = GPIO5, no RTS/CTS
```

**Important correction found on hardware:** the baud field decodes to `0xE1000` (= 921600 as a
plain integer), but the panel's *actual* emitted bit rate is **115200** — i.e. that value ÷8. Trust
115200 for interop. See [../stove/uart2-mainboard-link.md](../stove/uart2-mainboard-link.md) for how
this was measured. So the effective UART2 config is **115200 8N1**, TX = GPIO4, RX = GPIO5.

## Response-parser error oracle

The panel narrates why it rejects a mainboard reply, via these strings — extremely useful when
tuning an emulated mainboard. Reference locations (DROM):

| String | Referenced from | Meaning |
|--------|-----------------|---------|
| `Timeout %d` | — | no reply received on UART2 |
| `No x16 - %d` | `0x400d3980` | reply length not a multiple of 16 |
| `CRC Err` | `0x400d36a4` | Modbus CRC did not validate |
| `OtherAddress` | — | wrong slave address in the reply |
| `Incomplete Message` | `0x400d36e5` | reply shorter than expected |
| `Function Error` | `0x400d3717` | unexpected function code |
| `Exeption: %d` | — | reply was a Modbus exception (code logged) |
| `Errata Message`, `Errata TRANS` | — | other malformed-reply paths |

The parser processes a reply through a validator subroutine (called from ~`0x400d3645`) that returns
a result code routed to the strings above. On success it stores the register data and updates state
in `0x3ffcd224` (error counters at offsets `0x60` / `0x62`).

## Cloud (MQTT) client config

Built at `0x400d5049` (`esp_mqtt_client_config_t`). Values documented in
[../stove/cloud-mqtt.md](../stove/cloud-mqtt.md). The pinned CA is saved as
`firmware/mcz_broker_ca_digicert.pem`.

## Other useful symbols / strings

- Modbus helpers: `modbus_read`, `modbus_write`, `modbus_Mqtt_read` (the panel is the Modbus master).
- BLE text-provisioning parser (separate from the `0xABF0` control service): field separator byte
  `0xB4`, scanf pattern `%[^=]=%[^\xB4]\xB4%s`. Commands: `SCAN=` (returns the Wi-Fi list),
  `CREDENTIALS=<ssid>\xB4<password>`, `CONNECT` (→ `CONNECTION_OK` / `ERR%03d`), `STATUS`
  (→ `CONNECTED:<ip>` / `UNCONNECTED`), `UNCONNECT`, `POTA=START` (panel OTA), `BOTA=START`
  (board OTA). This is Wi-Fi provisioning + firmware-update only, **not** stove control.
- Local network surfaces: a `tcp_server` / `tcp_svr` socket used only to push firmware during
  POTA/BOTA. There is **no** local HTTP or WebSocket server (the WebSocket strings in the image are
  an outbound *client*). The only local control surface is the `0xABF0` BLE service.
- Console strings: `Connect`, `MA %02x:…`, `rejected Nm0`, `Found Pair`, `Already saved`,
  `ADV start`, `disconnected`, `Dev: %d - %d`, `Bonded devices number/list`, `Timeout %d`,
  `Letto resetParam %d`.
