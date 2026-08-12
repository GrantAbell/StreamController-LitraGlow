"""Manager, group, hotplug and lifecycle tests."""

from __future__ import annotations

import time

import pytest

from litra_glow.litra.manager import LitraDeviceManager
from litra_glow.litra.models import TARGET_MODE_ALL, TARGET_MODE_SELECTED

from .fakes import FakeLight, FakeTransport

# Long enough for the worker to drain a few commands, short enough to keep the
# suite quick. The manager's coalescing window is 50 ms.
SETTLE = 0.45


def settle(seconds: float = SETTLE) -> None:
    time.sleep(seconds)


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


def start(manager) -> None:
    manager.start()
    settle(0.3)


# -- discovery ------------------------------------------------------------


def test_discovers_a_connected_light(manager, lights):
    lights.append(FakeLight("AAA"))
    start(manager)
    assert manager.get_device_ids() == ["AAA"]


def test_discovers_several_lights_by_serial(manager, lights):
    lights.extend([FakeLight("AAA"), FakeLight("BBB")])
    start(manager)
    assert sorted(manager.get_device_ids()) == ["AAA", "BBB"]


def test_light_connected_after_start_is_found(manager, lights):
    start(manager)
    assert manager.get_device_ids() == []

    lights.append(FakeLight("LATE"))
    # Discovery runs every ~1.5 s.
    settle(2.0)
    assert manager.get_device_ids() == ["LATE"]


def test_unplug_marks_the_light_gone(manager, lights):
    light = FakeLight("AAA")
    lights.append(light)
    start(manager)
    settle()
    assert manager.get_state("AAA").connected

    light.present = False
    settle(2.0)
    assert manager.get_state("AAA").connected is False


def test_replug_restores_control_automatically(manager, lights):
    light = FakeLight("AAA", power=True, brightness=200, temperature=5000)
    lights.append(light)
    start(manager)
    settle()

    light.present = False
    settle(2.0)
    assert not manager.get_state("AAA").connected

    light.present = True
    settle(2.5)

    state = manager.get_state("AAA")
    assert state.connected
    # State is re-read from the device rather than assumed.
    assert state.brightness_lm == 200
    assert state.temperature_k == 5000


# -- state reads ----------------------------------------------------------


def test_reads_all_three_properties(manager, lights):
    lights.append(FakeLight("AAA", power=True, brightness=180, temperature=3400))
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    state = manager.get_state("AAA")
    assert state.power is True
    assert state.brightness_lm == 180
    assert state.temperature_k == 3400


def test_changes_made_on_the_light_itself_are_picked_up(manager, lights):
    light = FakeLight("AAA", brightness=100)
    lights.append(light)
    start(manager)
    manager.watch(["AAA"])
    settle()

    # Simulate someone pressing the buttons on the light.
    light.brightness = 220
    settle(1.6)
    assert manager.get_state("AAA").brightness_lm == 220


def test_unwatched_devices_are_not_polled(manager, lights):
    light = FakeLight("AAA")
    lights.append(light)
    start(manager)
    settle()
    light.writes.clear()

    settle(1.6)
    assert light.writes == [], "a light nobody is watching should cost no traffic"


# -- writes ---------------------------------------------------------------


def test_set_power_on_and_off(manager, lights):
    light = FakeLight("AAA", power=False)
    lights.append(light)
    start(manager)

    manager.set_power(["AAA"], True)
    settle()
    assert light.power is True

    manager.set_power(["AAA"], False)
    settle()
    assert light.power is False


def test_set_brightness_percent_maps_to_lumens(manager, lights):
    light = FakeLight("AAA")
    lights.append(light)
    start(manager)

    manager.set_brightness_percent(["AAA"], 0)
    settle()
    assert light.brightness == 20

    manager.set_brightness_percent(["AAA"], 100)
    settle()
    assert light.brightness == 250


def test_set_temperature_normalises(manager, lights):
    light = FakeLight("AAA")
    lights.append(light)
    start(manager)

    manager.set_temperature(["AAA"], 4250)
    settle()
    assert light.temperature == 4200


# -- toggle ---------------------------------------------------------------


def test_toggle_uses_the_real_device_state(manager, lights):
    light = FakeLight("AAA", power=True)
    lights.append(light)
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    manager.toggle_power(["AAA"])
    settle()
    assert light.power is False

    manager.toggle_power(["AAA"])
    settle()
    assert light.power is True


def test_toggle_of_a_mixed_group_turns_everything_on(manager, lights):
    on = FakeLight("ON", power=True)
    off = FakeLight("OFF", power=False)
    lights.extend([on, off])
    start(manager)
    manager.refresh_now(["ON", "OFF"])
    settle()

    manager.toggle_power(["ON", "OFF"])
    settle()
    assert on.power is True
    assert off.power is True


def test_toggle_of_an_all_on_group_turns_everything_off(manager, lights):
    first = FakeLight("A", power=True)
    second = FakeLight("B", power=True)
    lights.extend([first, second])
    start(manager)
    manager.refresh_now(["A", "B"])
    settle()

    manager.toggle_power(["A", "B"])
    settle()
    assert first.power is False
    assert second.power is False


# -- relative group adjustments --------------------------------------------


def test_relative_brightness_preserves_each_light_offset(manager, lights):
    dim = FakeLight("DIM", brightness=100)
    bright = FakeLight("BRIGHT", brightness=200)
    lights.extend([dim, bright])
    start(manager)
    manager.refresh_now(["DIM", "BRIGHT"])
    settle()

    manager.adjust_brightness(["DIM", "BRIGHT"], 20)
    settle()

    assert dim.brightness == 120
    assert bright.brightness == 220


def test_relative_temperature_preserves_each_light_offset(manager, lights):
    warm = FakeLight("WARM", temperature=3000)
    cool = FakeLight("COOL", temperature=5000)
    lights.extend([warm, cool])
    start(manager)
    manager.refresh_now(["WARM", "COOL"])
    settle()

    manager.adjust_temperature(["WARM", "COOL"], 200)
    settle()

    assert warm.temperature == 3200
    assert cool.temperature == 5200


def test_fixed_value_makes_every_target_match(manager, lights):
    dim = FakeLight("DIM", brightness=100)
    bright = FakeLight("BRIGHT", brightness=200)
    lights.extend([dim, bright])
    start(manager)
    settle()

    manager.set_brightness(["DIM", "BRIGHT"], 150)
    settle()

    assert dim.brightness == 150
    assert bright.brightness == 150


def test_relative_adjustment_clamps_at_the_ends(manager, lights):
    light = FakeLight("AAA", brightness=245)
    lights.append(light)
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    manager.adjust_brightness(["AAA"], 50)
    settle()
    assert light.brightness == 250


# -- rapid dial movement ----------------------------------------------------


def test_rapid_dial_ticks_reach_the_final_value(manager, lights):
    light = FakeLight("AAA", brightness=20)
    lights.append(light)
    start(manager)
    manager.refresh_now(["AAA"])
    settle()
    light.writes.clear()

    for _ in range(10):
        manager.adjust_brightness(["AAA"], 20)

    settle(1.0)
    # 20 + 10*20 = 220, clamped well inside the range.
    assert light.brightness == 220


def test_rapid_dial_ticks_are_coalesced_into_fewer_writes(manager, lights):
    light = FakeLight("AAA", brightness=20)
    lights.append(light)
    start(manager)
    manager.refresh_now(["AAA"])
    settle()
    light.writes.clear()

    for _ in range(10):
        manager.adjust_brightness(["AAA"], 20)
    settle(1.0)

    # Without coalescing this would be 10 writes; the point is that it is fewer
    # while still landing on the final value.
    assert len(light.writes) < 10


def test_desired_value_is_visible_immediately(manager, lights):
    light = FakeLight("AAA", brightness=100)
    lights.append(light)
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    manager.set_brightness(["AAA"], 200)
    # No settle: the display must not wait for the USB write.
    assert manager.get_state("AAA").brightness_lm == 200


# -- targeting -------------------------------------------------------------


def test_all_target_resolves_live(manager, lights):
    lights.append(FakeLight("AAA"))
    start(manager)

    assert manager.resolve_targets(TARGET_MODE_ALL, []) == ["AAA"]

    lights.append(FakeLight("BBB"))
    settle(2.0)
    assert sorted(manager.resolve_targets(TARGET_MODE_ALL, [])) == ["AAA", "BBB"]


def test_selected_target_ignores_absent_devices(manager, lights):
    lights.append(FakeLight("AAA"))
    start(manager)

    resolved = manager.resolve_targets(TARGET_MODE_SELECTED, ["AAA", "GHOST"])
    assert resolved == ["AAA"]


# -- group state -----------------------------------------------------------


def test_group_state_of_one_device(manager, lights):
    lights.append(FakeLight("AAA", power=True, brightness=120, temperature=4200))
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    group = manager.get_group_state(TARGET_MODE_SELECTED, ["AAA"])
    assert group.all_connected
    assert group.power is True
    assert group.brightness_lm == 120
    assert not group.mixed_brightness


def test_group_state_reports_mixed_values(manager, lights):
    lights.extend(
        [
            FakeLight("A", power=True, brightness=100, temperature=3000),
            FakeLight("B", power=False, brightness=200, temperature=5000),
        ]
    )
    start(manager)
    manager.refresh_now(["A", "B"])
    settle()

    group = manager.get_group_state(TARGET_MODE_SELECTED, ["A", "B"])
    assert group.mixed_power
    assert group.mixed_brightness
    assert group.mixed_temperature


def test_group_state_with_one_disconnected_device(manager, lights):
    lights.append(FakeLight("AAA", power=True, brightness=120))
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    group = manager.get_group_state(TARGET_MODE_SELECTED, ["AAA", "GHOST"])
    assert group.any_connected
    assert not group.all_connected
    assert group.connected_count == 1
    assert group.device_count == 2
    # The one light that is present still reports its real value.
    assert group.brightness_lm == 120


def test_group_state_with_nothing_configured(manager):
    start(manager)
    group = manager.get_group_state(TARGET_MODE_SELECTED, [])
    assert group.device_count == 0
    assert not group.any_connected


# -- failure isolation -------------------------------------------------------


def test_one_failing_light_does_not_stop_the_others(manager, lights):
    good = FakeLight("GOOD")
    bad = FakeLight("BAD")
    lights.extend([good, bad])
    start(manager)
    settle()

    bad.present = False  # fails on the next write
    manager.set_brightness(["GOOD", "BAD"], 150)
    settle()

    assert good.brightness == 150


def test_a_light_that_cannot_be_opened_is_reported_as_a_permission_problem(
    manager, lights
):
    light = FakeLight("AAA")
    light.openable = False
    lights.append(light)
    start(manager)
    manager.refresh_now(["AAA"])
    settle()

    assert manager.permission_error is not None
    assert not manager.get_state("AAA").connected


def test_commands_for_an_unknown_device_are_harmless(manager):
    start(manager)
    manager.set_power(["NOPE"], True)
    manager.adjust_brightness(["NOPE"], 10)
    settle()  # must not raise


# -- listeners and lifecycle -------------------------------------------------


def test_listeners_are_notified_on_change(manager, lights):
    lights.append(FakeLight("AAA"))
    calls = []
    manager.add_listener(lambda: calls.append(1))
    start(manager)
    settle()
    assert calls, "a discovered device should notify listeners"


def test_removed_listeners_stop_being_called(manager, lights):
    lights.append(FakeLight("AAA"))
    calls = []

    def listener():
        calls.append(1)

    manager.add_listener(listener)
    start(manager)
    settle()

    manager.remove_listener(listener)
    before = len(calls)
    manager.set_power(["AAA"], True)
    settle()

    assert len(calls) == before


def test_a_failing_listener_does_not_break_the_others(manager, lights):
    lights.append(FakeLight("AAA"))
    survived = []

    manager.add_listener(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    manager.add_listener(lambda: survived.append(1))
    start(manager)
    settle()

    assert survived


def test_unwatch_is_balanced_across_actions(manager, lights):
    lights.append(FakeLight("AAA"))
    start(manager)

    # Two actions watching the same light; one goes away.
    manager.watch(["AAA"])
    manager.watch(["AAA"])
    manager.unwatch(["AAA"])
    assert "AAA" in manager._watched_ids()

    manager.unwatch(["AAA"])
    assert "AAA" not in manager._watched_ids()


def test_stop_closes_everything(manager, lights):
    lights.append(FakeLight("AAA"))
    start(manager)
    settle()

    manager.stop()
    assert manager.get_device_ids() == []
