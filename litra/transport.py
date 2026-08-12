"""Raw HID transport. The only module that touches the device.

Backend: direct /dev/hidraw I/O via os.open/read/write, chosen because the
StreamController Flatpak runtime ships no HIDAPI binding and hidraw is a plain
character device. This needs zero third-party packages and was proven working
both on the host and inside the Flatpak.

Enumeration reads sysfs, which exposes the serial number as HID_UNIQ without
opening the device -- useful because a light already opened by another process
can still be identified.

Nothing above this module may perform file or HID operations, and every OS
error is converted to a LitraError here.
"""

from __future__ import annotations

import errno
import os
import select
import time

from .errors import (
    LitraDisconnectedError,
    LitraHidError,
    LitraPermissionError,
)
from .models import PRODUCT_ID, VENDOR_ID, LitraDeviceInfo

HIDRAW_CLASS_PATH = "/sys/class/hidraw"

# Marks a Report ID (0x85) declaration of the HID++ long report (0x11) inside a
# report descriptor. Used to pick the vendor-specific interface instead of
# assuming every 046D:C900 interface is appropriate.
HIDPP_LONG_DESCRIPTOR_MARKER = b"\x85\x11"

DEFAULT_READ_TIMEOUT_S = 1.0
READ_BUFFER_SIZE = 64


class LitraTransport:
    """One open handle to one physical light.

    Not internally synchronised: LitraDevice owns the per-device lock that keeps
    reads and writes from interleaving.
    """

    def __init__(self) -> None:
        self._fd: int | None = None
        self._path: str | None = None

    # -- enumeration ------------------------------------------------------

    def enumerate_devices(self) -> list[LitraDeviceInfo]:
        """Return every connected Litra Glow interface we can talk HID++ to.

        Never raises for an unreadable node: a device we cannot inspect is simply
        not reported, and discovery keeps working for the rest.
        """
        found: list[LitraDeviceInfo] = []

        try:
            nodes = sorted(os.listdir(HIDRAW_CLASS_PATH))
        except OSError:
            return found

        for node in nodes:
            base = os.path.join(HIDRAW_CLASS_PATH, node, "device")
            uevent = self._read_uevent(os.path.join(base, "uevent"))

            ids = self._parse_hid_id(uevent.get("HID_ID", ""))
            if ids != (VENDOR_ID, PRODUCT_ID):
                continue

            descriptor = self._read_bytes(os.path.join(base, "report_descriptor"))
            # If any interface advertises the HID++ long report, only those are
            # candidates. If none do (unexpected descriptor), fall through and
            # accept the interface rather than losing the device entirely.
            if descriptor and HIDPP_LONG_DESCRIPTOR_MARKER not in descriptor:
                continue

            serial = uevent.get("HID_UNIQ") or None
            path = f"/dev/{node}"
            found.append(
                LitraDeviceInfo(
                    device_id=serial or path,
                    serial_number=serial,
                    path=path.encode("utf-8"),
                    vendor_id=VENDOR_ID,
                    product_id=PRODUCT_ID,
                )
            )

        return found

    def device_exists(self) -> bool:
        """True if the currently opened path still exists in sysfs."""
        return self._path is not None and os.path.exists(self._path)

    @staticmethod
    def _read_uevent(path: str) -> dict[str, str]:
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

    @staticmethod
    def _read_bytes(path: str) -> bytes:
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError:
            return b""

    @staticmethod
    def _parse_hid_id(hid_id: str) -> tuple[int, int] | None:
        # HID_ID is "bus:VVVVVVVV:PPPPPPPP" in hex.
        parts = hid_id.split(":")
        if len(parts) != 3:
            return None
        try:
            return int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            return None

    # -- lifecycle --------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self, device_path: bytes) -> None:
        self.close()
        path = os.fsdecode(device_path)
        try:
            self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as error:
            raise LitraPermissionError(
                f"cannot open {path}: permission denied. "
                "Install the udev rule from udev/99-litra-glow.rules."
            ) from error
        except FileNotFoundError as error:
            raise LitraDisconnectedError(f"{path} no longer exists") from error
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EPERM):
                raise LitraPermissionError(f"cannot open {path}: {error}") from error
            if error.errno in (errno.ENODEV, errno.ENOENT, errno.ENXIO):
                raise LitraDisconnectedError(f"cannot open {path}: {error}") from error
            raise LitraHidError(f"cannot open {path}: {error}") from error
        self._path = path

    def close(self) -> None:
        if self._fd is None:
            return
        try:
            os.close(self._fd)
        except OSError:
            # Closing a handle to an unplugged device can fail; nothing useful
            # is left to do about it.
            pass
        finally:
            self._fd = None
            self._path = None

    # -- I/O --------------------------------------------------------------

    def drain(self) -> None:
        """Discard queued reports left over from earlier commands.

        Every write is acknowledged, setters included, so an un-drained ACK
        would otherwise be read as the next command's response.
        """
        if self._fd is None:
            return
        while True:
            try:
                if not select.select([self._fd], [], [], 0)[0]:
                    return
                if not os.read(self._fd, READ_BUFFER_SIZE):
                    return
            except OSError:
                return

    def write_report(self, report: bytes) -> None:
        if self._fd is None:
            raise LitraDisconnectedError("write on a closed device")
        try:
            written = os.write(self._fd, report)
        except OSError as error:
            raise self._io_error("write", error) from error
        if written != len(report):
            raise LitraHidError(f"short write: {written}/{len(report)} bytes")

    def read_report(self, timeout_ms: int = int(DEFAULT_READ_TIMEOUT_S * 1000)) -> bytes | None:
        """Read one report, or None if nothing arrives before the timeout."""
        if self._fd is None:
            raise LitraDisconnectedError("read on a closed device")

        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                readable, _, _ = select.select([self._fd], [], [], remaining)
                if not readable:
                    return None
                data = os.read(self._fd, READ_BUFFER_SIZE)
            except OSError as error:
                raise self._io_error("read", error) from error
            if data:
                return data

    @staticmethod
    def _io_error(operation: str, error: OSError) -> Exception:
        if error.errno in (errno.ENODEV, errno.ENXIO, errno.ESHUTDOWN, errno.EIO):
            return LitraDisconnectedError(f"{operation} failed, device gone: {error}")
        if error.errno in (errno.EACCES, errno.EPERM):
            return LitraPermissionError(f"{operation} failed: {error}")
        return LitraHidError(f"{operation} failed: {error}")
