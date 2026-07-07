#!/usr/bin/env python3
"""Minimal single-attempt BLE connect to the panel; prints each step (flushed)."""
import asyncio
from bleak import BleakClient

ADDR = "A0:A3:B3:2C:F0:82"


async def main():
    print("step: creating client", flush=True)
    c = BleakClient(ADDR, timeout=12.0)
    try:
        print("step: connecting", flush=True)
        await c.connect()
        print("CONNECTED mtu=%s services=%d" % (c.mtu_size, len(list(c.services))), flush=True)
        for s in c.services:
            print("svc %s" % s.uuid, flush=True)
            for ch in s.characteristics:
                print("   ch %s %s" % (ch.uuid, ch.properties), flush=True)
    except Exception as e:
        print("FAILED: %s: %s" % (type(e).__name__, e), flush=True)
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass
        print("step: done", flush=True)


asyncio.run(main())
