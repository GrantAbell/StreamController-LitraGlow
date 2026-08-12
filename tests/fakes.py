"""A fake Litra that speaks the real wire protocol.

Modelled on the traffic captured from the physical device,
including the detail that bit the first probe: every write is
acknowledged, so an un-drained ACK can be mistaken for the next response.
Reproducing that here means the group and lifecycle tests exercise the same
drain/match logic the hardware forced us to write.
"""

from __future__ import annotations

import time

from litra_glow.litra.errors import LitraDisconnectedError, LitraPermissionError
from litra_glow.litra.models import LitraDeviceInfo
from litra_glow.litra.protocol import (
    FN_GET_BRIGHTNESS,
    FN_GET_POWER,
    FN_GET_TEMPERATURE,
    FN_SET_BRIGHTNESS,
    FN_SET_POWER,
    FN_SET_TEMPERATURE,
    HIDPP_DEVICE_INDEX_USB,
    HIDPP_REPORT_ID,
    LITRA_FEATURE_INDEX,
    REPORT_LENGTH,
    command,
)


def start(manager, settle: float = 0.3) -> None:
    """Start a manager after its lights are registered.

    Discovery only runs every ~1.5 s, so a manager started before the fake
    lights exist will not see them for the length of a normal test -- which
    silently turns assertions into no-ops. Always register lights first, then
    call this.
    """
    manager.start()
    time.sleep(settle)


class FakeLight:
    """The device's own state, shared between the transport and the test."""

    def __init__(self, serial: str, power=False, brightness=120, temperature=4200):
        self.serial = serial
        self.power = power
        self.brightness = brightness
        self.temperature = temperature
        self.present = True
        self.openable = True
        self.writes: list[bytes] = []


class FakeTransport:
    """Drop-in replacement for LitraTransport, backed by FakeLight objects."""

    #: Lights visible to every instance created from this class.
    registry: list[FakeLight] = []

    def __init__(self) -> None:
        self._light: FakeLight | None = None
        self._queue: list[bytes] = []
        self._open = False

    # -- enumeration --

    def enumerate_devices(self) -> list[LitraDeviceInfo]:
        return [
            LitraDeviceInfo(
                device_id=light.serial,
                serial_number=light.serial,
                path=f"/dev/fake/{light.serial}".encode(),
                vendor_id=0x046D,
                product_id=0xC900,
            )
            for light in self.registry
            if light.present
        ]

    # -- lifecycle --

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self, device_path: bytes) -> None:
        serial = device_path.decode().rsplit("/", 1)[-1]
        for light in self.registry:
            if light.serial == serial and light.present:
                if not light.openable:
                    raise LitraPermissionError(f"cannot open {serial}")
                self._light = light
                self._open = True
                self._queue = []
                return
        raise LitraDisconnectedError(f"{serial} not present")

    def close(self) -> None:
        self._open = False
        self._light = None
        self._queue = []

    # -- I/O --

    def drain(self) -> None:
        self._queue = []

    def write_report(self, report: bytes) -> None:
        if not self._open or self._light is None:
            raise LitraDisconnectedError("write on closed device")
        if not self._light.present:
            raise LitraDisconnectedError("device gone")

        self._light.writes.append(report)
        function_byte = report[3]
        params = report[4:]

        def reply(*values: int) -> None:
            response = bytearray(REPORT_LENGTH)
            response[0] = HIDPP_REPORT_ID
            response[1] = HIDPP_DEVICE_INDEX_USB
            response[2] = LITRA_FEATURE_INDEX
            response[3] = function_byte
            for index, value in enumerate(values):
                response[4 + index] = value
            self._queue.append(bytes(response))

        if function_byte == command(FN_GET_POWER):
            reply(1 if self._light.power else 0)
        elif function_byte == command(FN_SET_POWER):
            self._light.power = params[0] == 1
            reply(0)  # ACK, parameters zeroed -- exactly like the real device
        elif function_byte == command(FN_GET_BRIGHTNESS):
            reply((self._light.brightness >> 8) & 0xFF, self._light.brightness & 0xFF)
        elif function_byte == command(FN_SET_BRIGHTNESS):
            self._light.brightness = (params[0] << 8) | params[1]
            reply(0, 0)
        elif function_byte == command(FN_GET_TEMPERATURE):
            reply((self._light.temperature >> 8) & 0xFF, self._light.temperature & 0xFF)
        elif function_byte == command(FN_SET_TEMPERATURE):
            self._light.temperature = (params[0] << 8) | params[1]
            reply(0, 0)

    def read_report(self, timeout_ms: int = 400) -> bytes | None:
        if not self._open:
            raise LitraDisconnectedError("read on closed device")
        if self._queue:
            return self._queue.pop(0)
        return None
