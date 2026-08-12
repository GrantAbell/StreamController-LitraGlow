"""Power behaviour tests.

The action class itself imports GTK and StreamController, so what is tested here
is the rule it delegates to, plus the manager behaviour behind it.
"""

from __future__ import annotations

import time

import pytest

from litra_glow.litra.manager import LitraDeviceManager
from litra_glow.litra.semantics import group_toggle_target

from .fakes import FakeLight, FakeTransport, start

SETTLE = 0.45


@pytest.fixture
def lights():
    FakeTransport.registry = []
    yield FakeTransport.registry
    FakeTransport.registry = []


@pytest.fixture
def manager(lights):
    instance = LitraDeviceManager(transport_factory=FakeTransport)
    yield instance
    instance.stop()


# -- group toggle rule ----------------------------------------------------


def test_all_on_toggles_off():
    assert group_toggle_target([True, True]) is False


def test_all_off_toggles_on():
    assert group_toggle_target([False, False]) is True


def test_mixed_group_toggles_on():
    # Not "each light inverts" -- the whole group resolves to on.
    assert group_toggle_target([True, False]) is True


def test_single_light_toggle():
    assert group_toggle_target([True]) is False
    assert group_toggle_target([False]) is True


def test_unknown_state_toggles_on():
    assert group_toggle_target([None]) is True
    assert group_toggle_target([]) is True


def test_partially_unknown_group_ignores_the_unknown_member():
    assert group_toggle_target([True, None]) is False
    assert group_toggle_target([False, None]) is True


# -- through the manager --------------------------------------------------


def test_explicit_on_ignores_current_state(manager, lights):
    already_on = FakeLight("A", power=True)
    off = FakeLight("B", power=False)
    lights.extend([already_on, off])
    start(manager)
    time.sleep(SETTLE)

    manager.set_power(["A", "B"], True)
    time.sleep(SETTLE)

    assert already_on.power is True
    assert off.power is True


def test_explicit_off_ignores_current_state(manager, lights):
    on = FakeLight("A", power=True)
    already_off = FakeLight("B", power=False)
    lights.extend([on, already_off])
    start(manager)
    time.sleep(SETTLE)

    manager.set_power(["A", "B"], False)
    time.sleep(SETTLE)

    assert on.power is False
    assert already_off.power is False


def test_toggle_leaves_a_disconnected_member_alone(manager, lights):
    present = FakeLight("A", power=True)
    lights.append(present)
    start(manager)
    time.sleep(SETTLE)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    manager.toggle_power(["A", "GHOST"])
    time.sleep(SETTLE)

    assert present.power is False


def test_power_does_not_change_brightness_or_temperature(manager, lights):
    light = FakeLight("A", power=False, brightness=137, temperature=3300)
    lights.append(light)
    start(manager)
    time.sleep(SETTLE)

    manager.set_power(["A"], True)
    time.sleep(SETTLE)

    assert light.brightness == 137
    assert light.temperature == 3300
