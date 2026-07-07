#!/usr/bin/env python3
"""Bond MCZ_EP on Windows using raw WinRT pairing (Just Works, no PIN),
BEFORE attempting GATT. Then connect and dump services."""
import asyncio, traceback
from bleak import BleakScanner, BleakClient

NAME = "MCZ_EP"

async def winrt_pair(bt_addr_int):
    # Raw WinRT DeviceInformation pairing — does not require GATT service discovery.
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import (
        DevicePairingKinds, DevicePairingResultStatus,
    )
    dev = await BluetoothLEDevice.from_bluetooth_address_async(bt_addr_int)
    if dev is None:
        print("  winrt: could not get BluetoothLEDevice"); return False
    info = dev.device_information
    pairing = info.pairing
    print(f"  is_paired={pairing.is_paired} can_pair={pairing.can_pair}")
    if pairing.is_paired:
        print("  already paired"); return True
    custom = pairing.custom
    def on_req(sender, args):
        print("  pairing request kind:", args.pairing_kind)
        args.accept()  # Just Works
    custom.add_pairing_requested(on_req)
    res = await custom.pair_async(DevicePairingKinds.CONFIRM_ONLY)
    print("  pair status:", res.status)
    return res.status == DevicePairingResultStatus.PAIRED

async def main():
    print("== scan ==")
    target = None
    found = await BleakScanner.discover(timeout=12.0, return_adv=True)
    for addr, (d, adv) in found.items():
        nm = adv.local_name or d.name or ""
        if NAME.lower() in nm.lower():
            print(f"FOUND {addr} rssi={adv.rssi}")
            target = (addr, d)
    if not target:
        print("!! not found"); return
    addr, d = target
    bt_int = int(addr.replace(":", ""), 16)

    print("\n== pair (raw winrt) ==")
    try:
        ok = await winrt_pair(bt_int)
        print("  paired:", ok)
    except Exception:
        traceback.print_exc()

    print("\n== connect after pairing ==")
    try:
        async with BleakClient(d, timeout=30.0) as c:
            print("  CONNECTED mtu=", c.mtu_size)
            for s in c.services:
                print("  svc", s.uuid)
                for ch in s.characteristics:
                    print("     ch", ch.uuid, ch.properties)
    except Exception as e:
        print("  connect failed:", type(e).__name__, e)

asyncio.run(main())
