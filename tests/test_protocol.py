"""Protocol unit tests.

The expected byte strings are the ones captured from the physical Litra Glow,
so a regression here means the plugin has stopped speaking the language the
hardware actually answered to.
"""

from __future__ import annotations

import pytest

from litra_glow.litra.errors import LitraProtocolError
from litra_glow.litra.protocol import (
    FN_GET_BRIGHTNESS,
    FN_GET_POWER,
    FN_GET_TEMPERATURE,
    REPORT_LENGTH,
    SOFTWARE_ID,
    LitraProtocol,
    command,
)


@pytest.fixture
def protocol():
    return LitraProtocol()


def hexbytes(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


def padded(prefix: str) -> bytes:
    """A 20-byte report starting with `prefix`, zero-padded."""
    head = hexbytes(prefix)
    return head + bytes(REPORT_LENGTH - len(head))


# -- function byte construction -----------------------------------------------


def test_command_builds_function_byte():
    assert command(0x1) == 0x1C
    assert command(0x4) == 0x4C
    assert command(0x9) == 0x9C


def test_software_id_is_the_low_nibble():
    for function in range(0x0, 0x10):
        assert command(function) & 0x0F == SOFTWARE_ID


# -- exact encodings ---------------------------------------------------------


def test_power_on_bytes(protocol):
    assert protocol.encode_set_power(True) == padded("11 FF 04 1C 01")


def test_power_off_bytes(protocol):
    assert protocol.encode_set_power(False) == padded("11 FF 04 1C 00")


def test_minimum_brightness_bytes(protocol):
    assert protocol.encode_set_brightness(20) == padded("11 FF 04 4C 00 14")


def test_maximum_brightness_bytes(protocol):
    assert protocol.encode_set_brightness(250) == padded("11 FF 04 4C 00 FA")


def test_temperature_2700_bytes(protocol):
    assert protocol.encode_set_temperature(2700) == padded("11 FF 04 9C 0A 8C")


def test_temperature_4200_bytes(protocol):
    assert protocol.encode_set_temperature(4200) == padded("11 FF 04 9C 10 68")


def test_temperature_6500_bytes(protocol):
    assert protocol.encode_set_temperature(6500) == padded("11 FF 04 9C 19 64")


def test_getters_carry_no_parameters(protocol):
    assert protocol.encode_get_power() == padded("11 FF 04 0C")
    assert protocol.encode_get_brightness() == padded("11 FF 04 3C")
    assert protocol.encode_get_temperature() == padded("11 FF 04 8C")


@pytest.mark.parametrize(
    "report",
    [
        "encode_get_power",
        "encode_get_brightness",
        "encode_get_temperature",
    ],
)
def test_every_report_is_the_right_length(protocol, report):
    assert len(getattr(protocol, report)()) == REPORT_LENGTH


def test_setter_reports_are_the_right_length(protocol):
    assert len(protocol.encode_set_power(True)) == REPORT_LENGTH
    assert len(protocol.encode_set_brightness(120)) == REPORT_LENGTH
    assert len(protocol.encode_set_temperature(4200)) == REPORT_LENGTH


# -- clamping and normalisation happen before the wire --------------------


def test_brightness_is_clamped_when_encoded(protocol):
    assert protocol.encode_set_brightness(0) == padded("11 FF 04 4C 00 14")
    assert protocol.encode_set_brightness(9999) == padded("11 FF 04 4C 00 FA")


def test_temperature_is_normalised_when_encoded(protocol):
    # 4250 K is not a valid step; it must be snapped before being sent.
    assert protocol.encode_set_temperature(4250) == protocol.encode_set_temperature(4200)
    assert protocol.encode_set_temperature(1000) == protocol.encode_set_temperature(2700)
    assert protocol.encode_set_temperature(9000) == protocol.encode_set_temperature(6500)


# -- golden responses --------------------------------------------------------


def test_decode_power_on(protocol):
    assert protocol.decode_power(padded("11 FF 04 0C 01")) is True


def test_decode_power_off(protocol):
    assert protocol.decode_power(padded("11 FF 04 0C 00")) is False


def test_decode_brightness(protocol):
    assert protocol.decode_brightness(padded("11 FF 04 3C 00 78")) == 120
    assert protocol.decode_brightness(padded("11 FF 04 3C 00 FA")) == 250


def test_decode_temperature(protocol):
    assert protocol.decode_temperature(padded("11 FF 04 8C 10 68")) == 4200
    assert protocol.decode_temperature(padded("11 FF 04 8C 0A 8C")) == 2700
    assert protocol.decode_temperature(padded("11 FF 04 8C 19 64")) == 6500


def test_decode_brightness_accepts_values_set_by_the_physical_dial(protocol):
    # The light reported 56 lm during hardware testing; a read must not reject
    # a value the device itself produced.
    assert protocol.decode_brightness(padded("11 FF 04 3C 00 38")) == 56


# -- malformed input is contained ----------------------------------------------


def test_missing_response_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(None)


def test_truncated_response_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_brightness(hexbytes("11 FF 04 3C 00"))


def test_wrong_report_id_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(padded("10 FF 04 0C 01"))


def test_wrong_device_index_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(padded("11 01 04 0C 01"))


def test_wrong_feature_index_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(padded("11 FF 08 0C 01"))


def test_foreign_software_id_raises(protocol):
    # Another HID++ client's traffic must never be decoded as ours.
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(padded("11 FF 04 01 01"))


def test_response_to_a_different_function_raises(protocol):
    # A stale SET ACK must not be accepted as a GET response -- the exact bug
    # the hardware probe exposed.
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(padded("11 FF 04 1C 00"))


def test_out_of_range_power_value_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_power(padded("11 FF 04 0C 07"))


def test_absurd_temperature_raises(protocol):
    with pytest.raises(LitraProtocolError):
        protocol.decode_temperature(padded("11 FF 04 8C FF FF"))


# -- response matching ----------------------------------------------------


def test_matches_only_its_own_function(protocol):
    assert protocol.matches(padded("11 FF 04 0C 01"), FN_GET_POWER)
    assert not protocol.matches(padded("11 FF 04 1C 00"), FN_GET_POWER)
    assert protocol.matches(padded("11 FF 04 3C 00 78"), FN_GET_BRIGHTNESS)
    assert protocol.matches(padded("11 FF 04 8C 10 68"), FN_GET_TEMPERATURE)


def test_matches_rejects_short_and_foreign_reports(protocol):
    assert not protocol.matches(b"", FN_GET_POWER)
    assert not protocol.matches(padded("11 FF 08 0C 01"), FN_GET_POWER)
