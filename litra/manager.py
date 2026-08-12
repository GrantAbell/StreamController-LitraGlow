"""LitraDeviceManager: the one hardware owner for the whole plugin.

Exactly one of these exists, owned by LitraGlowPlugin. Actions never open a
device, never touch HID, and never block: they call a method here, it returns
immediately, and a single worker thread performs the USB work in order.

Three background responsibilities:

  worker    - executes queued commands, per-device ordered
  discovery - enumerates every ~1.5 s, handling plug and unplug
  refresh   - re-reads devices that actions are actually watching, every ~1 s

Desired state is what makes a dial usable: a turn updates the
desired value and notifies listeners immediately, while the worker writes toward
the newest value. Rapid rotation therefore costs one USB write per coalescing
window instead of one per tick, and the final value always reaches the light.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from .device import LitraDevice
from .errors import LitraError, LitraPermissionError
from .models import (
    TARGET_MODE_ALL,
    GroupState,
    LitraDeviceInfo,
    LitraState,
    clamp_lumens,
    normalize_kelvin,
    percent_to_lumens,
)
from .log import log
from .semantics import group_toggle_target
from .transport import LitraTransport

DISCOVERY_INTERVAL_S = 1.5
REFRESH_INTERVAL_S = 1.0

# How long a same-property write is held so a burst of dial ticks collapses into
# one USB write. Short enough to feel immediate, long enough to matter during a
# fast spin.
COALESCE_WINDOW_S = 0.05

# Devices with no listener are not polled, so a page the user is not looking at
# costs nothing.
StateListener = Callable[[], None]


class _Command:
    """A queued unit of work for one device."""

    __slots__ = ("device_id", "kind", "run")

    def __init__(self, device_id: str, kind: str, run: Callable[[LitraDevice], None]) -> None:
        self.device_id = device_id
        self.kind = kind
        self.run = run


class LitraDeviceManager:
    def __init__(self, transport_factory: Callable[[], LitraTransport] = LitraTransport) -> None:
        self._transport_factory = transport_factory
        self._enumerator = transport_factory()

        self._devices: dict[str, LitraDevice] = {}
        self._devices_lock = threading.RLock()

        # Desired values not yet written. device_id -> {"brightness": int, ...}
        self._desired: dict[str, dict[str, object]] = {}
        self._desired_lock = threading.Lock()

        self._queue: "queue.Queue[_Command | None]" = queue.Queue()
        self._listeners: list[StateListener] = []
        self._listeners_lock = threading.Lock()

        # device_id -> number of actions currently interested in it
        self._watch_counts: dict[str, int] = {}
        self._watch_lock = threading.Lock()

        self._permission_error: str | None = None

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()

        for name, target in (
            ("litra-worker", self._worker_loop),
            ("litra-discovery", self._discovery_loop),
            ("litra-refresh", self._refresh_loop),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

        # Discover synchronously enough that the first render has something to
        # show, without blocking the caller on USB reads.
        self._queue.put(_Command("", "discover", lambda _: None))

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()
        with self._devices_lock:
            for device in self._devices.values():
                device.disconnect()
            self._devices.clear()
        self._started = False

    # -- listeners --------------------------------------------------------

    def add_listener(self, listener: StateListener) -> None:
        with self._listeners_lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: StateListener) -> None:
        with self._listeners_lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _notify(self) -> None:
        """Tell every action to redraw. Never called with a device lock held."""
        with self._listeners_lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                log.exception("Litra: state listener failed")

    # -- watching (drives which devices get polled) -----------------------

    def watch(self, device_ids: list[str]) -> None:
        with self._watch_lock:
            for device_id in device_ids:
                self._watch_counts[device_id] = self._watch_counts.get(device_id, 0) + 1

    def unwatch(self, device_ids: list[str]) -> None:
        with self._watch_lock:
            for device_id in device_ids:
                if device_id in self._watch_counts:
                    self._watch_counts[device_id] -= 1
                    if self._watch_counts[device_id] <= 0:
                        del self._watch_counts[device_id]

    def _watched_ids(self) -> set[str]:
        with self._watch_lock:
            watching_all = TARGET_MODE_ALL in self._watch_counts
            explicit = {k for k in self._watch_counts if k != TARGET_MODE_ALL}
        if watching_all:
            return set(self.get_device_ids())
        return explicit

    # -- queries ----------------------------------------------------------

    def get_devices(self) -> list[LitraDeviceInfo]:
        with self._devices_lock:
            return [device.info for device in self._devices.values()]

    def get_device_ids(self) -> list[str]:
        with self._devices_lock:
            return list(self._devices.keys())

    def get_state(self, device_id: str) -> LitraState:
        with self._devices_lock:
            device = self._devices.get(device_id)
        if device is None:
            return LitraState(connected=False)

        state = device.state
        # Show the value the user just dialled in, not the one the worker has
        # got round to writing, so the display never lags the input.
        with self._desired_lock:
            desired = dict(self._desired.get(device_id, {}))
        if "brightness" in desired:
            state.brightness_lm = int(desired["brightness"])
        if "temperature" in desired:
            state.temperature_k = int(desired["temperature"])
        if "power" in desired:
            state.power = bool(desired["power"])
        return state

    @property
    def permission_error(self) -> str | None:
        """Set when a light is present but cannot be opened."""
        return self._permission_error

    def resolve_targets(self, target_mode: str, device_ids: list[str]) -> list[str]:
        """Turn an action's settings into concrete device IDs.

        'all' resolves live, so lights connected later are included with no
        further configuration.
        """
        if target_mode == TARGET_MODE_ALL:
            return self.get_device_ids()
        available = set(self.get_device_ids())
        return [device_id for device_id in device_ids if device_id in available]

    def get_group_state(self, target_mode: str, device_ids: list[str]) -> GroupState:
        """Aggregate several lights for a single key or dial."""
        if target_mode == TARGET_MODE_ALL:
            targets = self.get_device_ids()
            configured_count = len(targets)
        else:
            targets = list(device_ids)
            configured_count = len(targets)

        group = GroupState(device_count=configured_count)
        connected_states: list[LitraState] = []

        for device_id in targets:
            state = self.get_state(device_id)
            group.states[device_id] = state
            if state.connected:
                connected_states.append(state)

        group.connected_count = len(connected_states)
        group.any_connected = bool(connected_states)
        group.all_connected = bool(targets) and len(connected_states) == len(targets)

        def collapse(values: list) -> tuple[object | None, bool]:
            present = [value for value in values if value is not None]
            if not present:
                return None, False
            first = present[0]
            return first, any(value != first for value in present)

        group.power, group.mixed_power = collapse([s.power for s in connected_states])
        group.brightness_lm, group.mixed_brightness = collapse(
            [s.brightness_lm for s in connected_states]
        )
        group.temperature_k, group.mixed_temperature = collapse(
            [s.temperature_k for s in connected_states]
        )
        return group

    # -- public commands (all non-blocking) -------------------------------

    def set_power(self, targets: list[str], enabled: bool) -> None:
        for device_id in targets:
            self._set_desired(device_id, "power", bool(enabled))
            self._submit(device_id, "power", self._make_power_write(device_id))
        self._notify()

    def toggle_power(self, targets: list[str]) -> None:
        """Toggle as a group: all on -> all off, otherwise all on.

        This keeps a mixed group from simply inverting each member and staying
        mixed.
        """
        if not targets:
            return
        states = [self.get_state(device_id) for device_id in targets]
        powers = [state.power for state in states if state.connected]
        self.set_power(targets, group_toggle_target(powers))

    def set_brightness(self, targets: list[str], lumens: int) -> None:
        lumens = clamp_lumens(lumens)
        for device_id in targets:
            self._set_desired(device_id, "brightness", lumens)
            self._submit(device_id, "brightness", self._make_brightness_write(device_id))
        self._notify()

    def set_brightness_percent(self, targets: list[str], percent: float) -> None:
        self.set_brightness(targets, percent_to_lumens(percent))

    def adjust_brightness(self, targets: list[str], delta_lumens: int) -> None:
        """Relative change applied to each light's own current value.

        Two lights at different brightness keep their offset.
        """
        for device_id in targets:
            current = self._current_value(device_id, "brightness")
            if current is None:
                continue
            self._set_desired(device_id, "brightness", clamp_lumens(current + delta_lumens))
            self._submit(device_id, "brightness", self._make_brightness_write(device_id))
        self._notify()

    def adjust_brightness_percent(self, targets: list[str], delta_percent: float) -> None:
        # A percentage step is a fixed number of lumens, so the step size stays
        # constant across the range instead of shrinking near the bottom.
        delta_lumens = round((delta_percent / 100.0) * (250 - 20))
        self.adjust_brightness(targets, delta_lumens)

    def set_temperature(self, targets: list[str], kelvin: int) -> None:
        kelvin = normalize_kelvin(kelvin)
        for device_id in targets:
            self._set_desired(device_id, "temperature", kelvin)
            self._submit(device_id, "temperature", self._make_temperature_write(device_id))
        self._notify()

    def adjust_temperature(self, targets: list[str], delta_kelvin: int) -> None:
        for device_id in targets:
            current = self._current_value(device_id, "temperature")
            if current is None:
                continue
            self._set_desired(
                device_id, "temperature", normalize_kelvin(current + delta_kelvin)
            )
            self._submit(device_id, "temperature", self._make_temperature_write(device_id))
        self._notify()

    def identify(self, device_id: str) -> None:
        """Flash a light, then put it back exactly as it was."""
        self._submit(device_id, "identify", self._run_identify)

    def refresh_now(self, device_ids: list[str]) -> None:
        for device_id in device_ids:
            self._submit(device_id, "refresh", self._refresh_device)

    # -- desired state ----------------------------------------------------

    def _set_desired(self, device_id: str, key: str, value: object) -> None:
        with self._desired_lock:
            self._desired.setdefault(device_id, {})[key] = value

    def _take_desired(self, device_id: str, key: str) -> object | None:
        with self._desired_lock:
            values = self._desired.get(device_id)
            if not values or key not in values:
                return None
            value = values.pop(key)
            if not values:
                self._desired.pop(device_id, None)
            return value

    def _current_value(self, device_id: str, key: str) -> int | None:
        """The value a relative adjustment should build on.

        Prefers the pending desired value so consecutive dial ticks accumulate
        instead of all reading the same stale device value.
        """
        with self._desired_lock:
            desired = self._desired.get(device_id, {})
            if key in desired:
                return int(desired[key])

        state = self.get_state(device_id)
        if not state.connected:
            return None
        return state.brightness_lm if key == "brightness" else state.temperature_k

    # -- command plumbing -------------------------------------------------

    def _submit(self, device_id: str, kind: str, run: Callable[[LitraDevice], None]) -> None:
        if not self._started:
            log.debug(f"Litra: command {kind} dropped, manager not started")
            return
        self._queue.put(_Command(device_id, kind, run))

    def _make_power_write(self, device_id: str) -> Callable[[LitraDevice], None]:
        def run(device: LitraDevice) -> None:
            value = self._take_desired(device_id, "power")
            if value is None:
                return
            device.set_power(bool(value))

        return run

    def _make_brightness_write(self, device_id: str) -> Callable[[LitraDevice], None]:
        def run(device: LitraDevice) -> None:
            value = self._take_desired(device_id, "brightness")
            if value is None:
                # A later command in the same burst already wrote it.
                return
            device.set_brightness(int(value))

        return run

    def _make_temperature_write(self, device_id: str) -> Callable[[LitraDevice], None]:
        def run(device: LitraDevice) -> None:
            value = self._take_desired(device_id, "temperature")
            if value is None:
                return
            device.set_temperature(int(value))

        return run

    def _refresh_device(self, device: LitraDevice) -> None:
        device.refresh()

    def _run_identify(self, device: LitraDevice) -> None:
        saved = device.state
        try:
            for power, hold in device.identify_frames():
                device.set_power(power)
                # The device lock is released between frames, so this sleep does
                # not block other lights.
                time.sleep(hold)
        finally:
            if saved.power is not None:
                device.set_power(saved.power)
            if saved.brightness_lm is not None:
                device.set_brightness(saved.brightness_lm)
            if saved.temperature_k is not None:
                device.set_temperature(saved.temperature_k)

    # -- worker -----------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                command = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if command is None:
                break

            if command.kind == "discover":
                self._discover()
                self._queue.task_done()
                continue

            # Give a burst of same-property commands a moment to collapse.
            if command.kind in ("brightness", "temperature"):
                time.sleep(COALESCE_WINDOW_S)

            self._execute(command)
            self._queue.task_done()

    def _execute(self, command: _Command) -> None:
        with self._devices_lock:
            device = self._devices.get(command.device_id)
        if device is None:
            return

        try:
            if not device.connected:
                device.connect()
            command.run(device)
        except LitraPermissionError as error:
            self._permission_error = str(error)
            log.warning(f"Litra: {error}")
            device.disconnect()
        except LitraError as error:
            # One light failing must not stop the others.
            log.warning(f"Litra: {command.kind} on {command.device_id} failed: {error}")
            device.disconnect()
        except Exception:
            log.exception(f"Litra: unexpected failure on {command.device_id}")
            device.disconnect()

        self._notify()

    # -- discovery --------------------------------------------------------

    def _discovery_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._discover()
            except Exception:
                log.exception("Litra: discovery failed")
            self._stop.wait(DISCOVERY_INTERVAL_S)

    def _discover(self) -> None:
        """Reconcile the device table with what is physically present.

        Devices are matched by serial number, so a replug reattaches to the same
        configured target even if the hidraw path changed.
        """
        found = {info.device_id: info for info in self._enumerator.enumerate_devices()}
        changed = False

        with self._devices_lock:
            for device_id, info in found.items():
                device = self._devices.get(device_id)
                if device is None:
                    device = LitraDevice(info, self._transport_factory())
                    self._devices[device_id] = device
                    changed = True
                    log.info(f"Litra: discovered {info.display_name}")
                elif device.info.path != info.path:
                    # Same light, new node: reopen against the new path.
                    device.update_info(info)
                    device.disconnect()
                    changed = True

            for device_id in list(self._devices):
                if device_id not in found:
                    device = self._devices.pop(device_id)
                    device.disconnect()
                    changed = True
                    log.info(f"Litra: {device_id} disconnected")

        if found:
            # A device is present again, so any earlier permission complaint is
            # no longer necessarily true; it will be re-set if opening fails.
            if self._permission_error and any(
                self._devices[d].connected for d in self._devices
            ):
                self._permission_error = None

        for device_id in found:
            with self._devices_lock:
                device = self._devices.get(device_id)
            if device is not None and not device.connected:
                self._submit(device_id, "refresh", self._refresh_device)

        if changed:
            self._notify()

    # -- periodic refresh -------------------------------------------------

    def _refresh_loop(self) -> None:
        """Re-read watched devices so physical dial changes show up.

        Centralised here so ten actions on one light cost one read, not ten.
        """
        while not self._stop.is_set():
            self._stop.wait(REFRESH_INTERVAL_S)
            if self._stop.is_set():
                break
            try:
                for device_id in self._watched_ids():
                    # Skip a device with writes still pending: refreshing now
                    # would read a value the user has already moved past.
                    with self._desired_lock:
                        if self._desired.get(device_id):
                            continue
                    self._submit(device_id, "refresh", self._refresh_device)
            except Exception:
                log.exception("Litra: refresh scheduling failed")
