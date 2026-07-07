# Mainboard emulator (bench)

A stand-in for the combustion mainboard so the panel firmware works on the bench without a real
stove. It runs on a **second ESP32** (MicroPython), wired to the panel's UART2, and answers the
panel's AES-wrapped Modbus polls. With it running, the panel stops its mainboard-timeout loop and
comes up over BLE.

- The link it speaks → [../uart2-mainboard-link.md](../uart2-mainboard-link.md)
- The envelope / crypto → [../../docs/frame-format.md](../../docs/frame-format.md),
  [../../docs/aes-encryption.md](../../docs/aes-encryption.md)
- The readiness gate (resolved; the emulator doesn't open it) → [../../docs/ble-readiness-gate-RESOLVED.md](../../docs/ble-readiness-gate-RESOLVED.md)

## What it does

`emulator_main.py` (MicroPython) on the emulator board:

1. Opens UART2 at **115200 8N1**, TX = GPIO4, RX = GPIO5 (it auto-probes which pin carries the
   panel's transmit).
2. For each incoming burst: AES-decrypts it, verifies the `TOKEN`, strips PKCS#7 padding, checks the
   Modbus CRC, and parses the PDU.
3. Builds a reply PDU (answers vendor read `0x41`, echoes write-multiple `0x10`), re-wraps it in the
   same `[counter][TOKEN][PDU][CRC][pad]` AES envelope, and transmits it.
4. Logs each request/response to its own USB console so you can watch it work.

It uses MicroPython's built-in `cryptolib` for AES, so no extra packages are needed on the board.

## Hardware & wiring

Two ESP32 boards (both CP210x USB-serial in the reference bench):

| Board | Role |
|-------|------|
| Panel board (with antenna) | runs the panel firmware; is the BLE server |
| Emulator board | runs MicroPython + `emulator_main.py` |

```
   Panel GPIO4 (TX2) ──────►  Emulator GPIO5 (RX2)
   Panel GPIO5 (RX2) ◄──────  Emulator GPIO4 (TX2)
   Panel GND         ───────  Emulator GND
```

Keep leads short and the ground solid (see [../uart2-mainboard-link.md](../uart2-mainboard-link.md)).

## Flashing MicroPython + deploying the emulator

`micropython_esp32.bin` in this folder is a stock MicroPython ESP32 build (`ESP32_GENERIC`,
downloaded from micropython.org). Flash it, then upload the script:

```bash
# flash MicroPython (erases the board)
python -m esptool --chip esp32 --port <EMU_PORT> --baud 460800 \
    write-flash --erase-all 0x1000 micropython_esp32.bin

# copy the emulator as main.py so it runs on boot
python -m mpremote connect <EMU_PORT> fs cp emulator_main.py :main.py
python -m mpremote connect <EMU_PORT> reset
```

Watch it run by reading the emulator's own console, or (better) watch the **panel's** console to see
how it reacts — see the error oracle in
[../../panel/disassembly-notes.md](../../panel/disassembly-notes.md) and
[../../docs/status-and-open-questions.md](../../docs/status-and-open-questions.md).

> The emulator board is fully restorable to panel firmware from
> [`../../panel/firmware/flash_4mb/`](../../panel/firmware/flash_4mb/) if you want to repurpose it.

## Current state

The emulator reliably decrypts and answers the panel's polls; the panel accepts its short replies
cleanly (no parser error) and reaches BLE advertising. **This is all the emulator needs to do** — it
does not, and *cannot*, open the panel's BLE readiness gate, because that gate is a
commissioning/pairing gate rather than a mainboard-health check and reads no mainboard register to
decide it. There is no "mainboard ready" reply to find; the earlier open item was mis-framed. See
[../../docs/ble-readiness-gate-RESOLVED.md](../../docs/ble-readiness-gate-RESOLVED.md) for the
byte-level proof and the real unblock (put the panel through pairing/provisioning).

**Confirmed in the full end-to-end run (2026-07-07):** with the gate bypassed on the dev board (the
gate-open build) and this emulator answering, a BLE client's encrypted register **reads and write**
round-tripped all the way to the emulator and back — the panel relayed them over UART2, the emulator
answered (`REQ func=0x41 reg=0x02bc → RESP pdu=42B`), and the replies reached the client on `0xABF2`.
The emulator returns placeholder register values, so the client sees `state=Off` / `room=0.0 °C` —
real values need a real mainboard. Capture: `captures/gateopen_emulator.log`.

Verify the emulator's reply framing offline (no hardware) with
[`diagnostics/verify_reply.py`](diagnostics/verify_reply.py).

## `diagnostics/` — how the link was decoded

These are the throwaway scripts used to reverse the UART2 link, kept as a record of method. Most run
**on the emulator board via MicroPython** (`python -m mpremote connect <PORT> run <script>.py`); a
few run on the **laptop** (Windows Python). They were written to be run from the project root during
development, so some paths may need adjusting.

| Script | Runs on | Purpose |
|--------|---------|---------|
| `uart2_sniff.py` | laptop | passive serial sniffer: hex/ASCII dump + Modbus parse |
| `wiring_test.py` | laptop | proves the two boards' UART2 lines are cross-wired |
| `baud_sweep.py` | laptop | sweep bauds on a port, score by CRC-valid Modbus frames |
| `measure_baud.py` | board | rough baud estimate from pulse timing |
| `measure_baud2.py` | board | precise bit-period histogram (found ~115200) |
| `measure_cadence.py` | board | burst cadence (found ~1 burst/second) |
| `capture_pulses.py` | board | record the raw edge-timing train |
| `decode_pulses.py` | laptop | offline UART decode of a captured pulse train |
| `test_uart_variants.py` | board | on-device baud × invert sweep, scored by CRC |
| `fine_sweep.py` | board | fine baud sweep with polarity + bit-phase recovery |
| `raw_dump.py` | board | clean raw capture at 115200, hex/ASCII/Modbus |
| `decrypt_bursts.py` | laptop | offline AES-decrypt of captured bursts (the breakthrough) |
| `capture_decode.py` | board | on-device decrypt + enumerate the panel's request types |
| `verify_reply.py` | laptop | offline "panel-side" verifier: build/check a reply frame (len %16, TOKEN, CRC, register extraction) |

The decisive chain was: `measure_baud2` (→115200) → `raw_dump` (clean 32-byte bursts) →
`decrypt_bursts` (they decrypt with the BLE keys → same envelope) → `capture_decode` (enumerate the
`0x41`/`0x10` requests).
