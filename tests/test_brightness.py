"""Brightness tests."""

from __future__ import annotations

import time

import pytest

from litra_glow.litra.manager import LitraDeviceManager
from litra_glow.litra.models import (
    MAX_LUMENS,
    MIN_LUMENS,
    clamp_lumens,
    lumens_to_percent,
    percent_to_lumens,
)
from litra_glow.litra.semantics import (
    KEY_MODE_DECREASE,
    KEY_MODE_INCREASE,
    KEY_MODE_SET,
    brightness_dial_delta,
    brightness_key_delta,
)

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


# -- percent mapping ---------------------------------------------------------


def test_zero_percent_is_the_minimum_lumens():
    assert percent_to_lumens(0) == 20


def test_hundred_percent_is_the_maximum_lumens():
    assert percent_to_lumens(100) == 250


def test_fifty_percent_is_the_midpoint():
    assert percent_to_lumens(50) == 135


def test_percent_below_zero_clamps():
    assert percent_to_lumens(-50) == MIN_LUMENS


def test_percent_above_hundred_clamps():
    assert percent_to_lumens(500) == MAX_LUMENS


def test_percent_round_trips():
    for percent in range(0, 101):
        assert lumens_to_percent(percent_to_lumens(percent)) == percent


def test_lumens_to_percent_clamps():
    assert lumens_to_percent(0) == 0
    assert lumens_to_percent(9999) == 100


def test_clamp_lumens_holds_the_device_range():
    assert clamp_lumens(0) == MIN_LUMENS
    assert clamp_lumens(19) == MIN_LUMENS
    assert clamp_lumens(251) == MAX_LUMENS
    assert clamp_lumens(120) == 120


def test_zero_percent_is_not_power_off():
    # Dimmest is still a lit light; powering off is a separate operation.
    assert percent_to_lumens(0) > 0


# -- key modes ------------------------------------------------------------


def test_increase_gives_a_positive_delta():
    assert brightness_key_delta(KEY_MODE_INCREASE, 5) == 5


def test_decrease_gives_a_negative_delta():
    assert brightness_key_delta(KEY_MODE_DECREASE, 5) == -5


def test_set_value_is_not_relative():
    assert brightness_key_delta(KEY_MODE_SET, 5) is None


def test_step_sign_is_ignored():
    assert brightness_key_delta(KEY_MODE_DECREASE, -5) == -5


# -- dial direction ----------------------------------------------------------


def test_clockwise_brightens():
    assert brightness_dial_delta(True, 5) == 5


def test_counter_clockwise_dims():
    assert brightness_dial_delta(False, 5) == -5


def test_dial_step_is_configurable():
    for step in (1, 2, 5, 10):
        assert brightness_dial_delta(True, step) == step


# -- through the manager --------------------------------------------------


def test_set_value_writes_the_exact_percentage(manager, lights):
    light = FakeLight("A", brightness=20)
    lights.append(light)
    start(manager)
    time.sleep(SETTLE)

    manager.set_brightness_percent(["A"], 60)
    time.sleep(SETTLE)
    assert light.brightness == percent_to_lumens(60)


def test_increase_then_decrease_returns_to_the_start(manager, lights):
    light = FakeLight("A", brightness=120)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    manager.adjust_brightness_percent(["A"], 10)
    time.sleep(SETTLE)
    raised = light.brightness

    manager.adjust_brightness_percent(["A"], -10)
    time.sleep(SETTLE)

    assert raised > 120
    assert light.brightness == 120


def test_increase_stops_at_the_maximum(manager, lights):
    light = FakeLight("A", brightness=240)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    for _ in range(5):
        manager.adjust_brightness_percent(["A"], 10)
    time.sleep(1.0)

    assert light.brightness == MAX_LUMENS


def test_decrease_stops_at_the_minimum(manager, lights):
    light = FakeLight("A", brightness=30)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    for _ in range(5):
        manager.adjust_brightness_percent(["A"], -10)
    time.sleep(1.0)

    assert light.brightness == MIN_LUMENS


def test_rapid_dial_changes_land_on_the_right_value(manager, lights):
    light = FakeLight("A", brightness=20)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    # 20 ticks of 5% = +100% from the bottom.
    for _ in range(20):
        manager.adjust_brightness_percent(["A"], 5)
    time.sleep(1.2)

    assert light.brightness == MAX_LUMENS


def test_a_percentage_step_is_a_constant_number_of_lumens(manager, lights):
    """A 5% step must feel the same at the bottom and the top of the range."""
    low = FakeLight("LOW", brightness=40)
    high = FakeLight("HIGH", brightness=200)
    lights.extend([low, high])
    start(manager)
    manager.refresh_now(["LOW", "HIGH"])
    time.sleep(SETTLE)

    manager.adjust_brightness_percent(["LOW", "HIGH"], 5)
    time.sleep(SETTLE)

    assert light_delta(low, 40) == light_delta(high, 200)


def light_delta(light: FakeLight, before: int) -> int:
    return light.brightness - before
