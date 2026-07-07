# Captures (evidence trail)

Raw serial/BLE logs kept as a record of what the hardware actually did. Not needed to use the
project — they back up the claims in the docs. Names are roughly chronological within each topic.

| File | What it shows |
|------|---------------|
| `panel_com39_boot.log`, `serial_live.log`, `serial_after_erase.log` | Panel firmware boot sequences on the bench (reaching `ADV start`, the `Timeout`/`Dev:` lines) |
| `dump_windows.log`, `dump_windows2.log`, `dump_after_erase.log` | esptool flash read/erase sessions |
| `panel_connect.log`, `panel_connect_test.log`, `panel_filtered.log`, `connect_during_serial.log` | Panel console during BLE connect attempts on the **stock** app — the `Connect` / `MA …` / `rejected Nm0` reject loop (the "before" state) |
| `ble_dump.log`, `ble_test.log`, `ble_test2.log`, `ble_test3.log` | BLE client connect/scan attempts from the laptop |
| `gateopen_panel_console.log`, `gateopen_ble_session.log`, `gateopen_emulator.log` | **Gate-open bench validation (2026-07-07):** the "after" state. Panel running `app_ota0_gateopen.bin` boots cleanly to `ADV start`, then `Connect` holds an accepted ~19 s session (**no `rejected Nm0`**); the BLE client enumerates `0xABF0` and round-trips encrypted register reads **and** a write; the emulator answers the panel's polls throughout. See [`../docs/ble-readiness-gate-RESOLVED.md`](../docs/ble-readiness-gate-RESOLVED.md#bench-validation-done-2026-07-07). |
| `win_diag.log`, `win_pair.log` | Windows BLE diagnostics |
| `pulses_capture.txt` | A raw UART2 edge-timing train captured during baud discovery (input to `decode_pulses.py`) |
