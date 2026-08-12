"""HID++ packet encoding and decoding for the Litra Glow.

This layer is pure: it turns intent into bytes and bytes into values, and knows
nothing about files, threads, or StreamController. Every constant on the wire is
defined here once so no action ever writes a literal like 0x4C.

The function codes below were verified against a physical Litra Glow by
probe_litra.py.
"""

from __future__ import annotations

from .errors import LitraProtocolError
from .models import clamp_lumens, normalize_kelvin

HIDPP_REPORT_ID = 0x11
HIDPP_DEVICE_INDEX_USB = 0xFF
LITRA_FEATURE_INDEX = 0x04
REPORT_LENGTH = 20

# The low nibble of the function byte. A dedicated nonzero software ID keeps our
# traffic distinguishable from another HID++ client's.
SOFTWARE_ID = 0x0C

# High nibble of the function byte. Getters sit one below their setter.
FN_GET_POWER = 0x0
FN_SET_POWER = 0x1
FN_GET_BRIGHTNESS = 0x3
FN_SET_BRIGHTNESS = 0x4
FN_GET_TEMPERATURE = 0x8
FN_SET_TEMPERATURE = 0x9

# Offsets within a report.
OFFSET_REPORT_ID = 0
OFFSET_DEVICE_INDEX = 1
OFFSET_FEATURE_INDEX = 2
OFFSET_FUNCTION = 3
OFFSET_PARAMS = 4


def command(function: int) -> int:
    """Build a function byte: high nibble function, low nibble software ID."""
    return (function << 4) | SOFTWARE_ID


def _build(function: int, *params: int) -> bytes:
    report = bytearray(REPORT_LENGTH)
    report[OFFSET_REPORT_ID] = HIDPP_REPORT_ID
    report[OFFSET_DEVICE_INDEX] = HIDPP_DEVICE_INDEX_USB
    report[OFFSET_FEATURE_INDEX] = LITRA_FEATURE_INDEX
    report[OFFSET_FUNCTION] = command(function)
    for offset, value in enumerate(params):
        report[OFFSET_PARAMS + offset] = value & 0xFF
    return bytes(report)


class LitraProtocol:
    """Encoders and decoders for the six Litra operations."""

    # -- encoding ---------------------------------------------------------

    def encode_get_power(self) -> bytes:
        return _build(FN_GET_POWER)

    def encode_set_power(self, enabled: bool) -> bytes:
        return _build(FN_SET_POWER, 0x01 if enabled else 0x00)

    def encode_get_brightness(self) -> bytes:
        return _build(FN_GET_BRIGHTNESS)

    def encode_set_brightness(self, lumens: int) -> bytes:
        lumens = clamp_lumens(lumens)
        return _build(FN_SET_BRIGHTNESS, (lumens >> 8) & 0xFF, lumens & 0xFF)

    def encode_get_temperature(self) -> bytes:
        return _build(FN_GET_TEMPERATURE)

    def encode_set_temperature(self, kelvin: int) -> bytes:
        kelvin = normalize_kelvin(kelvin)
        return _build(FN_SET_TEMPERATURE, (kelvin >> 8) & 0xFF, kelvin & 0xFF)

    # -- validation -------------------------------------------------------

    def validate(self, report: bytes | None, function: int, min_length: int) -> bytes:
        """Check a response's framing before any value is read from it.

        Raises LitraProtocolError rather than letting a malformed packet reach
        the action layer.
        """
        if report is None:
            raise LitraProtocolError(f"no response to function 0x{function:X}")
        if len(report) < min_length:
            raise LitraProtocolError(
                f"response too short: {len(report)} bytes, need {min_length}"
            )
        if report[OFFSET_REPORT_ID] != HIDPP_REPORT_ID:
            raise LitraProtocolError(
                f"unexpected report ID 0x{report[OFFSET_REPORT_ID]:02X}"
            )
        if report[OFFSET_DEVICE_INDEX] != HIDPP_DEVICE_INDEX_USB:
            raise LitraProtocolError(
                f"unexpected device index 0x{report[OFFSET_DEVICE_INDEX]:02X}"
            )
        if report[OFFSET_FEATURE_INDEX] != LITRA_FEATURE_INDEX:
            raise LitraProtocolError(
                f"unexpected feature index 0x{report[OFFSET_FEATURE_INDEX]:02X}"
            )
        actual = report[OFFSET_FUNCTION]
        if (actual & 0x0F) != SOFTWARE_ID:
            raise LitraProtocolError(
                f"software ID mismatch: got 0x{actual & 0x0F:X}, expected 0x{SOFTWARE_ID:X}"
            )
        if actual != command(function):
            raise LitraProtocolError(
                f"function mismatch: got 0x{actual:02X}, expected 0x{command(function):02X}"
            )
        return report

    def matches(self, report: bytes, function: int) -> bool:
        """True if `report` is the response to `function`.

        Used by the transport to skip stale ACKs and other clients' traffic
        without raising.
        """
        if report is None or len(report) < OFFSET_PARAMS + 1:
            return False
        return (
            report[OFFSET_REPORT_ID] == HIDPP_REPORT_ID
            and report[OFFSET_FEATURE_INDEX] == LITRA_FEATURE_INDEX
            and report[OFFSET_FUNCTION] == command(function)
        )

    # -- decoding ---------------------------------------------------------

    def decode_power(self, report: bytes) -> bool:
        self.validate(report, FN_GET_POWER, OFFSET_PARAMS + 1)
        value = report[OFFSET_PARAMS]
        if value not in (0x00, 0x01):
            raise LitraProtocolError(f"invalid power value 0x{value:02X}")
        return value == 0x01

    def decode_brightness(self, report: bytes) -> int:
        self.validate(report, FN_GET_BRIGHTNESS, OFFSET_PARAMS + 2)
        value = (report[OFFSET_PARAMS] << 8) | report[OFFSET_PARAMS + 1]
        # The physical dial can leave the light outside the range we would ever
        # write, so accept a slightly wider band on read than on write and only
        # reject values that cannot be a brightness at all.
        if not 0 <= value <= 1000:
            raise LitraProtocolError(f"brightness {value} lm out of plausible range")
        return value

    def decode_temperature(self, report: bytes) -> int:
        self.validate(report, FN_GET_TEMPERATURE, OFFSET_PARAMS + 2)
        value = (report[OFFSET_PARAMS] << 8) | report[OFFSET_PARAMS + 1]
        if not 1000 <= value <= 10000:
            raise LitraProtocolError(f"temperature {value} K out of plausible range")
        return value
