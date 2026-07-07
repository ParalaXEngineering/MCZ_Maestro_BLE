# Captures (evidence trail)

The key serial/BLE logs that back the "validated end-to-end" claim. Not needed to *use* the project —
they're the record of what the hardware actually did. (The exploratory diagnostic logs from the
reverse-engineering sessions have been pruned; these are the load-bearing ones.)

| File | What it shows |
|------|---------------|
| `panel_connect_test.log` | **The "before" state.** Panel console during a BLE connect on the *stock* app — the `Connect` / `MA …` / `rejected Nm0` reject loop (the readiness gate refusing the session). |
| `gateopen_panel_console.log` | **The "after" state, panel side.** Panel running the gate-open build boots to `ADV start`, then `Connect` holds an accepted ~19 s session — **no `rejected Nm0`** — then a clean `disconnected`. |
| `gateopen_ble_session.log` | The "after" state, client side: the BLE client enumerates `0xABF0` and round-trips encrypted register reads **and** a write. |
| `gateopen_emulator.log` | The mainboard emulator answering the panel's 1 Hz polls throughout the accepted session (`REQ func=0x41 … → RESP …`). |

The gate-open validation run is written up in
[`../docs/reference/readiness-gate.md`](../docs/reference/readiness-gate.md#bench-validation--done-2026-07-07).
