#!/usr/bin/env python3
"""Hardware proof-of-concept.

Proves, against a physically connected Logitech Litra Glow:

    1. Enumerate 046D:C900
    2. Select the correct HID interface
    3. Read serial number
    4. Open by HID path
    5. GET power        6. SET power
    7. GET brightness   8. SET brightness
    9. GET temperature 10. SET temperature
   11. Close cleanly

This script is deliberately standalone: no plugin imports, no third-party
dependencies. It is the experiment that decides the transport strategy, so it
must run identically on the host and inside the StreamController Flatpak.

The original state of the light is restored before exiting.

Usage:
    python3 probe_litra.py
    flatpak run --command=python3 com.core447.StreamController probe_litra.py
"""

from __future__ import annotations

import os
import select
import sys
import time

VENDOR_ID = 0x046D
PRODUCT_ID = 0xC900

HIDPP_REPORT_ID = 0x11
HIDPP_DEVICE_INDEX_USB = 0xFF
LITRA_FEATURE_INDEX = 0x04
REPORT_LENGTH = 20
SOFTWARE_ID = 0x0C

# Function nibbles. The setters are already known; the getters are the
# hypothesis this probe exists to prove or disprove, so they are not simply
# inferred from the setters.
FN_GET_POWER = 0x0
FN_SET_POWER = 0x1
FN_GET_BRIGHTNESS = 0x3
FN_SET_BRIGHTNESS = 0x4
FN_GET_TEMPERATURE = 0x8
FN_SET_TEMPERATURE = 0x9

MIN_LUMENS, MAX_LUMENS = 20, 250
MIN_KELVIN, MAX_KELVIN = 2700, 6500

READ_TIMEOUT_S = 1.0

_passes: list[str] = []
_failures: list[str] = []


def step(number: int, name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {number:>2}. {name}"
    if detail:
        line += f" -> {detail}"
    print(line)
    (_passes if ok else _failures).append(f"{number}. {name}")


def command(function: int) -> int:
    """Build a HID++ function byte: high nibble function, low nibble software ID."""
    return (function << 4) | SOFTWARE_ID


def build(function: int, *params: int) -> bytes:
    report = bytearray(REPORT_LENGTH)
    report[0] = HIDPP_REPORT_ID
    report[1] = HIDPP_DEVICE_INDEX_USB
    report[2] = LITRA_FEATURE_INDEX
    report[3] = command(function)
    for offset, value in enumerate(params):
        report[4 + offset] = value
    return bytes(report)


# --------------------------------------------------------------------------
# 1-3. Enumeration via sysfs. No HIDAPI binding exists in the Flatpak runtime,
# and hidraw is a plain character device, so sysfs is both dependency-free and
# richer (it exposes the serial as HID_UNIQ without opening the device).
# --------------------------------------------------------------------------

HIDRAW_CLASS = "/sys/class/hidraw"


def parse_uevent(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, sep, value = line.strip().partition("=")
                if sep:
                    values[key] = value
    except OSError:
        pass
    return values


def enumerate_litra() -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    try:
        nodes = sorted(os.listdir(HIDRAW_CLASS))
    except OSError as error:
        print(f"  cannot list {HIDRAW_CLASS}: {error}")
        return found

    for node in nodes:
        base = os.path.join(HIDRAW_CLASS, node, "device")
        uevent = parse_uevent(os.path.join(base, "uevent"))
        hid_id = uevent.get("HID_ID", "")
        # HID_ID format: bus:VVVVVVVV:PPPPPPPP (hex, zero padded)
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        try:
            vid, pid = int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            continue
        if (vid, pid) != (VENDOR_ID, PRODUCT_ID):
            continue

        descriptor = b""
        try:
            with open(os.path.join(base, "report_descriptor"), "rb") as handle:
                descriptor = handle.read()
        except OSError:
            pass

        found.append(
            {
                "node": node,
                "path": f"/dev/{node}",
                "serial": uevent.get("HID_UNIQ") or None,
                "name": uevent.get("HID_NAME", ""),
                "phys": uevent.get("HID_PHYS", ""),
                "vendor_id": vid,
                "product_id": pid,
                "descriptor": descriptor,
            }
        )
    return found


def supports_hidpp_long(descriptor: bytes) -> bool:
    """True if the report descriptor declares the 0x11 (HID++ long) report.

    Encoded as Report ID (0x85) 0x11 somewhere in the descriptor. Used to pick
    the vendor-specific interface rather than assuming every c900 interface is
    appropriate.
    """
    return b"\x85\x11" in descriptor


# --------------------------------------------------------------------------
# 4-11. Raw hidraw I/O
# --------------------------------------------------------------------------


def write_report(fd: int, report: bytes) -> None:
    written = os.write(fd, report)
    if written != len(report):
        raise OSError(f"short write: {written}/{len(report)}")


def drain(fd: int) -> None:
    """Discard any reports still queued from earlier commands.

    Every write is acknowledged, including the setters, so a queued ACK will
    otherwise be mistaken for the next command's response.
    """
    while select.select([fd], [], [], 0)[0]:
        try:
            os.read(fd, 64)
        except OSError:
            return


def read_report(fd: int, function: int, timeout_s: float = READ_TIMEOUT_S) -> bytes | None:
    """Read the response to `function`, skipping traffic that is not ours.

    The device echoes the full function byte (function nibble + software ID) in
    byte 3, so responses can be matched to their request exactly.
    """
    expected = command(function)
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            return None
        data = os.read(fd, 64)
        if len(data) < 5:
            continue
        if data[0] != HIDPP_REPORT_ID:
            continue
        if data[2] != LITRA_FEATURE_INDEX:
            continue
        if data[3] != expected:
            # Another HID++ client's traffic, or a stale ACK.
            continue
        return data


def request(fd: int, function: int, *params: int) -> bytes | None:
    drain(fd)
    write_report(fd, build(function, *params))
    return read_report(fd, function)


def hexdump(data: bytes | None, count: int = 8) -> str:
    if data is None:
        return "<no response>"
    return " ".join(f"{byte:02X}" for byte in data[:count])


def main() -> int:
    print("Litra Glow hardware probe")
    print(f"python {sys.version.split()[0]}  |  pid {os.getpid()}")
    print()

    # --- 1. Enumerate ----------------------------------------------------
    devices = enumerate_litra()
    step(1, "Enumerate 046D:C900", bool(devices), f"{len(devices)} interface(s)")
    if not devices:
        print("\n  No Litra Glow found. Is it plugged in?")
        return 1
    for device in devices:
        print(
            f"        {device['path']}  serial={device['serial']}  "
            f"name={device['name']!r}  hidpp_long={supports_hidpp_long(device['descriptor'])}"
        )

    # --- 2. Select the correct interface ---------------------------------
    candidates = [d for d in devices if supports_hidpp_long(d["descriptor"])]
    if not candidates:
        # Fall back to the sole interface rather than giving up; record it.
        candidates = devices
        step(2, "Select correct HID interface", len(devices) == 1,
             "no descriptor match; fell back to only interface")
    else:
        step(2, "Select correct HID interface", True,
             f"{candidates[0]['path']} declares report 0x11")
    device = candidates[0]

    # --- 3. Serial number ------------------------------------------------
    serial = device["serial"]
    step(3, "Read serial number", bool(serial), str(serial))

    # --- 4. Open ---------------------------------------------------------
    try:
        fd = os.open(str(device["path"]), os.O_RDWR | os.O_NONBLOCK)
    except OSError as error:
        step(4, "Open by HID path", False, f"{type(error).__name__}: {error}")
        print("\n  Permission denied usually means the udev rule is missing.")
        return 1
    step(4, "Open by HID path", True, str(device["path"]))

    original_power = original_brightness = original_temperature = None
    exit_code = 0

    try:
        # --- 5. GET power ------------------------------------------------
        response = request(fd, FN_GET_POWER)
        ok = response is not None and len(response) >= 5 and response[4] in (0, 1)
        original_power = bool(response[4]) if ok else None
        step(5, "GET power", ok, f"{hexdump(response)}  => {original_power}")

        # --- 7. GET brightness -------------------------------------------
        response = request(fd, FN_GET_BRIGHTNESS)
        value = None
        if response is not None and len(response) >= 6:
            value = (response[4] << 8) | response[5]
        ok = value is not None and MIN_LUMENS <= value <= MAX_LUMENS
        original_brightness = value if ok else None
        step(7, "GET brightness", ok, f"{hexdump(response)}  => {value} lm")

        # --- 9. GET temperature ------------------------------------------
        response = request(fd, FN_GET_TEMPERATURE)
        value = None
        if response is not None and len(response) >= 6:
            value = (response[4] << 8) | response[5]
        ok = value is not None and MIN_KELVIN <= value <= MAX_KELVIN
        original_temperature = value if ok else None
        step(9, "GET temperature", ok, f"{hexdump(response)}  => {value} K")

        print()
        print(f"  Original state: power={original_power} "
              f"brightness={original_brightness} lm temperature={original_temperature} K")
        print("  Exercising setters (state will be restored)...")
        print()

        # --- 6. SET power ------------------------------------------------
        target_power = not original_power if original_power is not None else True
        acked = request(fd, FN_SET_POWER, int(target_power)) is not None
        time.sleep(0.2)
        response = request(fd, FN_GET_POWER)
        readback = bool(response[4]) if response is not None and len(response) >= 5 else None
        step(6, "SET power", acked and readback == target_power,
             f"wrote {target_power}, read back {readback}")

        # Leave the light on so the remaining writes are observable.
        request(fd, FN_SET_POWER, 1)
        time.sleep(0.2)

        # --- 8. SET brightness -------------------------------------------
        target_lumens = 120 if original_brightness != 120 else 200
        acked = request(fd, FN_SET_BRIGHTNESS, 0x00, target_lumens) is not None
        time.sleep(0.2)
        response = request(fd, FN_GET_BRIGHTNESS)
        readback = ((response[4] << 8) | response[5]) if response is not None and len(response) >= 6 else None
        step(8, "SET brightness", acked and readback == target_lumens,
             f"wrote {target_lumens} lm, read back {readback} lm")

        # --- 10. SET temperature -----------------------------------------
        target_kelvin = 4200 if original_temperature != 4200 else 5000
        acked = request(
            fd, FN_SET_TEMPERATURE,
            (target_kelvin >> 8) & 0xFF, target_kelvin & 0xFF,
        ) is not None
        time.sleep(0.2)
        response = request(fd, FN_GET_TEMPERATURE)
        readback = ((response[4] << 8) | response[5]) if response is not None and len(response) >= 6 else None
        step(10, "SET temperature", acked and readback == target_kelvin,
             f"wrote {target_kelvin} K, read back {readback} K")

    except OSError as error:
        print(f"\n  I/O error: {type(error).__name__}: {error}")
        exit_code = 1
    finally:
        # Restore original state before closing.
        try:
            if original_brightness is not None:
                write_report(fd, build(FN_SET_BRIGHTNESS, 0x00, original_brightness))
                time.sleep(0.15)
            if original_temperature is not None:
                write_report(
                    fd,
                    build(FN_SET_TEMPERATURE,
                          (original_temperature >> 8) & 0xFF,
                          original_temperature & 0xFF),
                )
                time.sleep(0.15)
            if original_power is not None:
                write_report(fd, build(FN_SET_POWER, int(original_power)))
                time.sleep(0.15)
            print("\n  Original state restored.")
        except OSError as error:
            print(f"\n  WARNING: could not restore state: {error}")

        try:
            os.close(fd)
            step(11, "Close cleanly", True)
        except OSError as error:
            step(11, "Close cleanly", False, str(error))
            exit_code = 1

    print()
    print(f"  {len(_passes)} passed, {len(_failures)} failed")
    if _failures:
        for name in _failures:
            print(f"    FAILED: {name}")
        return 1
    print("  Hardware proof complete: all 11 operations verified.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
