#!/usr/bin/env python3
"""Windows BLE connection diagnostic for MCZ_EP.
Scans, prints adv details, then tries several connect strategies with full errors."""
import asyncio, traceback
from bleak import BleakScanner, BleakClient

NAME = "MCZ_EP"

async def main():
    print("== scan ==")
    dev = None
    found = await BleakScanner.discover(timeout=12.0, return_adv=True)
    for addr, (d, adv) in found.items():
        nm = adv.local_name or d.name or ""
        if NAME.lower() in nm.lower():
            print(f"FOUND {addr} name={nm!r} rssi={adv.rssi}")
            print(f"   adv service_uuids={adv.service_uuids}")
            print(f"   adv manufacturer={adv.manufacturer_data}")
            print(f"   adv service_data={adv.service_data}")
            dev = d
    if not dev:
        print("!! MCZ_EP not found in scan"); return

    # Strategy A: connect via BLEDevice object, longer timeout, no pre-pair
    print("\n== A: plain connect (BLEDevice, 30s) ==")
    try:
        async with BleakClient(dev, timeout=30.0) as c:
            print("  CONNECTED, mtu=", c.mtu_size)
            for s in c.services:
                print("  svc", s.uuid)
            return
    except Exception as e:
        print("  A failed:", type(e).__name__, e)

    # Strategy B: pair first, then connect
    print("\n== B: pair() then connect ==")
    try:
        c = BleakClient(dev, timeout=30.0)
        await c.connect()
        print("  connected; pairing...")
        await c.pair()
        print("  PAIRED")
        for s in c.services:
            print("  svc", s.uuid)
        await c.disconnect()
        return
    except Exception:
        traceback.print_exc()

asyncio.run(main())
