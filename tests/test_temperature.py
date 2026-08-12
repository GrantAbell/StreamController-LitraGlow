"""Colour-temperature tests."""

from __future__ import annotations

import time

import pytest

from litra_glow.litra.manager import LitraDeviceManager
from litra_glow.litra.models import KELVIN_STEP, MAX_KELVIN, MIN_KELVIN, normalize_kelvin
from litra_glow.litra.semantics import (
    CLOCKWISE_COOLER,
    CLOCKWISE_WARMER,
    KEY_MODE_COOLER,
    KEY_MODE_SET,
    KEY_MODE_WARMER,
    temperature_dial_delta,
    temperature_key_delta,
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


# -- normalisation ---------------------------------------------------------


def test_supported_values_are_unchanged():
    for kelvin in (2700, 4200, 6500):
        assert normalize_kelvin(kelvin) == kelvin


def test_below_minimum_clamps():
    assert normalize_kelvin(1000) == MIN_KELVIN
    assert normalize_kelvin(2699) == MIN_KELVIN


def test_above_maximum_clamps():
    assert normalize_kelvin(9000) == MAX_KELVIN
    assert normalize_kelvin(6501) == MAX_KELVIN


def test_invalid_step_is_normalised():
    # 4250 K is not a valid setting; it must snap to a 100 K step.
    assert normalize_kelvin(4250) % KELVIN_STEP == 0
    assert normalize_kelvin(4250) in (4200, 4300)
    assert normalize_kelvin(4249) == 4200
    assert normalize_kelvin(4251) == 4300


def test_every_normalised_value_is_a_valid_step():
    for kelvin in range(2000, 7500, 37):
        result = normalize_kelvin(kelvin)
        assert result % KELVIN_STEP == 0
        assert MIN_KELVIN <= result <= MAX_KELVIN


# -- key modes ------------------------------------------------------------


def test_warmer_lowers_the_kelvin_value():
    assert temperature_key_delta(KEY_MODE_WARMER, 100) == -100


def test_cooler_raises_the_kelvin_value():
    assert temperature_key_delta(KEY_MODE_COOLER, 100) == 100


def test_set_value_is_not_relative():
    assert temperature_key_delta(KEY_MODE_SET, 100) is None


# -- dial direction and reversal -------------------------------------------


def test_clockwise_warmer_by_default():
    assert temperature_dial_delta(True, CLOCKWISE_WARMER, 100) == -100


def test_counter_clockwise_is_the_opposite():
    assert temperature_dial_delta(False, CLOCKWISE_WARMER, 100) == 100


def test_reversed_dial_direction():
    assert temperature_dial_delta(True, CLOCKWISE_COOLER, 100) == 100
    assert temperature_dial_delta(False, CLOCKWISE_COOLER, 100) == -100


def test_reversing_negates_every_direction():
    for clockwise in (True, False):
        normal = temperature_dial_delta(clockwise, CLOCKWISE_WARMER, 200)
        reversed_ = temperature_dial_delta(clockwise, CLOCKWISE_COOLER, 200)
        assert normal == -reversed_


def test_dial_step_choices():
    for step in (100, 200, 500):
        assert abs(temperature_dial_delta(True, CLOCKWISE_WARMER, step)) == step


# -- through the manager --------------------------------------------------


def test_set_value_writes_the_exact_temperature(manager, lights):
    light = FakeLight("A", temperature=3000)
    lights.append(light)
    start(manager)
    time.sleep(SETTLE)

    manager.set_temperature(["A"], 4200)
    time.sleep(SETTLE)
    assert light.temperature == 4200


def test_warmer_then_cooler_returns_to_the_start(manager, lights):
    light = FakeLight("A", temperature=4200)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    manager.adjust_temperature(["A"], -100)
    time.sleep(SETTLE)
    assert light.temperature == 4100

    manager.adjust_temperature(["A"], 100)
    time.sleep(SETTLE)
    assert light.temperature == 4200


def test_warming_stops_at_the_minimum(manager, lights):
    light = FakeLight("A", temperature=2800)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    for _ in range(5):
        manager.adjust_temperature(["A"], -100)
    time.sleep(1.0)

    assert light.temperature == MIN_KELVIN


def test_cooling_stops_at_the_maximum(manager, lights):
    light = FakeLight("A", temperature=6400)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    for _ in range(5):
        manager.adjust_temperature(["A"], 100)
    time.sleep(1.0)

    assert light.temperature == MAX_KELVIN


def test_an_out_of_step_value_never_reaches_the_light(manager, lights):
    light = FakeLight("A", temperature=4200)
    lights.append(light)
    start(manager)
    time.sleep(SETTLE)

    manager.set_temperature(["A"], 4250)
    time.sleep(SETTLE)

    assert light.temperature % KELVIN_STEP == 0


def test_rapid_dial_changes_land_on_the_right_value(manager, lights):
    light = FakeLight("A", temperature=4200)
    lights.append(light)
    start(manager)
    manager.refresh_now(["A"])
    time.sleep(SETTLE)

    for _ in range(10):
        manager.adjust_temperature(["A"], 100)
    time.sleep(1.2)

    assert light.temperature == 5200
