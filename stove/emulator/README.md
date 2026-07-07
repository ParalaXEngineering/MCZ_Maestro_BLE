# Mainboard emulator (bench)

A stand-in for the combustion mainboard so the panel firmware works on the bench without a real
stove. It runs on a **second ESP32** (MicroPython), wired to the panel's UART2, and answers the
panel's AES-wrapped Modbus polls. With it running, the panel stops its mainboard-timeout loop and
comes up over BLE.

- The link it speaks → [../../docs/reference/uart2-link.md](../../docs/reference/uart2-link.md)
- The envelope / crypto / registers → [../../docs/ble-protocol.md](../../docs/ble-protocol.md)
- Full bench recipe → [../../docs/setup.md](../../docs/setup.md)

## What it does

`emulator_main.py` on the emulator board:

1. Opens UART2 at **115200 8N1**, TX = GPIO4, RX = GPIO5 (auto-probes which pin carries the panel's
   transmit).
2. For each incoming burst: AES-decrypts it, verifies the `TOKEN`, strips PKCS#7 padding, checks the
   Modbus CRC, and parses the PDU.
3. Builds a reply PDU (answers vendor read `0x41`, echoes write-multiple `0x10`), re-wraps it in the
   same `[counter][TOKEN][PDU][CRC][pad]` AES envelope, and transmits it.
4. Logs each request/response to its USB console.

It uses MicroPython's built-in `cryptolib` for AES, so no extra packages are needed on the board.

## Wiring

Two ESP32 boards, UART2-to-UART2, 3.3 V logic, common ground:

```
   Panel GPIO4 (TX2) ──────►  Emulator GPIO5 (RX2)
   Panel GPIO5 (RX2) ◄──────  Emulator GPIO4 (TX2)
   Panel GND         ───────  Emulator GND
```

Keep leads short and the ground solid (see [../../docs/reference/uart2-link.md](../../docs/reference/uart2-link.md)).

## Flash MicroPython + deploy the emulator

`micropython_esp32.bin` here is a stock MicroPython ESP32 build (`ESP32_GENERIC`, from
micropython.org). Flash it, then upload the script as `main.py` so it runs on boot:

```bash
python -m esptool --chip esp32 --port <EMU_PORT> --baud 460800 \
    write-flash --erase-all 0x1000 micropython_esp32.bin
python -m mpremote connect <EMU_PORT> fs cp emulator_main.py :main.py
python -m mpremote connect <EMU_PORT> reset
```

Watch it via the emulator's own console, or (better) watch the **panel's** console to see how it
reacts — see the error oracle in
[../../docs/reference/firmware-disassembly.md](../../docs/reference/firmware-disassembly.md#response-parser-error-oracle).

> The emulator board is fully restorable to panel firmware from
> [`../../panel/firmware/flash_4mb/`](../../panel/firmware/flash_4mb/) if you want to repurpose it.

## What it can and can't do

The emulator reliably decrypts and answers the panel's polls; the panel accepts its short replies
cleanly (no parser error) and reaches BLE advertising. **This is all it needs to do** — it does not,
and *cannot*, open the panel's BLE [readiness gate](../../docs/reference/readiness-gate.md), because
that gate is a commissioning/pairing gate, not a mainboard-health check.

**In the full end-to-end run (2026-07-07):** with the gate bypassed on the dev board and this emulator
answering, a BLE client's encrypted register **reads and write** round-tripped all the way to the
emulator and back (`REQ func=0x41 reg=0x02bc → RESP pdu=42B`), reaching the client on `0xABF2`. The
emulator returns placeholder values, so the client sees `state=Off` / `room=0.0 °C` — real values need
a real mainboard. Capture: `../../captures/gateopen_emulator.log`.

Verify the reply framing offline (no hardware) with
[`diagnostics/verify_reply.py`](diagnostics/verify_reply.py).

## `diagnostics/` — how the link was decoded

Throwaway scripts used to reverse the UART2 link, kept as a record of method. Most run **on the
emulator board via MicroPython** (`python -m mpremote connect <PORT> run <script>.py`); a few run on
the **laptop**.

| Script | Runs on | Purpose |
|--------|---------|---------|
| `uart2_sniff.py` | laptop | passive serial sniffer: hex/ASCII + Modbus parse |
| `wiring_test.py` | laptop | proves the two boards' UART2 lines are cross-wired |
| `baud_sweep.py` | laptop | sweep bauds, score by CRC-valid Modbus frames |
| `measure_baud.py` / `measure_baud2.py` | board | baud estimate / precise bit-period histogram (found ~115200) |
| `measure_cadence.py` | board | burst cadence (found ~1 burst/second) |
| `capture_pulses.py` | board | record the raw edge-timing train |
| `decode_pulses.py` | laptop | offline UART decode of a captured pulse train |
| `test_uart_variants.py` / `fine_sweep.py` | board | baud × invert / bit-phase sweeps, scored by CRC |
| `raw_dump.py` | board | clean raw capture at 115200, hex/ASCII/Modbus |
| `decrypt_bursts.py` | laptop | offline AES-decrypt of captured bursts (the breakthrough) |
| `capture_decode.py` | board | on-device decrypt + enumerate the panel's request types |
| `verify_reply.py` | laptop | offline "panel-side" reply verifier (len %16, TOKEN, CRC, registers) |

The decisive chain: `measure_baud2` (→115200) → `raw_dump` (clean 32-byte bursts) → `decrypt_bursts`
(they decrypt with the BLE keys → same envelope) → `capture_decode` (enumerate the `0x41`/`0x10`
requests).
