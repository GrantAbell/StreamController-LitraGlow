"""One physical Litra Glow: transport + protocol + the per-device lock.

All HID access for a single light is serialised here, so a brightness write, a
temperature write, and a state read can never interleave on the same handle.
The lock is held only for the exchange itself -- never while
rendering, sleeping, or touching GTK.
"""

from __future__ import annotations

import threading

from .errors import LitraDisconnectedError, LitraProtocolError
from .models import LitraDeviceInfo, LitraState, clamp_lumens, normalize_kelvin
from .protocol import (
    FN_GET_BRIGHTNESS,
    FN_GET_POWER,
    FN_GET_TEMPERATURE,
    LitraProtocol,
)
from .transport import LitraTransport

# A response normally arrives within a few milliseconds. This bound only exists
# so a wedged device cannot stall the worker thread.
EXCHANGE_TIMEOUT_MS = 400

# How many foreign/stale reports to skip before giving up on a response.
MAX_SKIPPED_REPORTS = 8


class LitraDevice:
    """A single light. Every public method is safe to call from the worker."""

    def __init__(self, info: LitraDeviceInfo, transport: LitraTransport | None = None) -> None:
        self.info = info
        self.protocol = LitraProtocol()
        self._transport = transport if transport is not None else LitraTransport()
        self._lock = threading.Lock()
        self._state = LitraState()

    # -- identity ---------------------------------------------------------

    @property
    def device_id(self) -> str:
        return self.info.device_id

    @property
    def state(self) -> LitraState:
        """A snapshot; callers must not mutate the device's own state."""
        with self._lock:
            return self._state.copy()

    @property
    def connected(self) -> bool:
        return self._state.connected

    def update_info(self, info: LitraDeviceInfo) -> None:
        """Adopt a new HID path for the same light after a replug."""
        self.info = info

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        with self._lock:
            if self._transport.is_open:
                return
            self._transport.open(self.info.path)
            self._state.connected = True

    def disconnect(self) -> None:
        with self._lock:
            self._transport.close()
            self._state.connected = False
            # Values are stale the moment the light is gone; do not keep showing
            # them as if they were live.
            self._state.power = None
            self._state.brightness_lm = None
            self._state.temperature_k = None

    # -- exchange ---------------------------------------------------------

    def _exchange(self, request: bytes, function: int) -> bytes:
        """Write a request and return its matching response.

        Caller must hold the lock. Stale ACKs and other HID++ clients' traffic
        are skipped by matching the full function byte.
        """
        if not self._transport.is_open:
            raise LitraDisconnectedError(f"{self.device_id} is not open")

        self._transport.drain()
        self._transport.write_report(request)

        for _ in range(MAX_SKIPPED_REPORTS):
            report = self._transport.read_report(EXCHANGE_TIMEOUT_MS)
            if report is None:
                break
            if self.protocol.matches(report, function):
                return report
        raise LitraProtocolError(
            f"no response to function 0x{function:X} from {self.device_id}"
        )

    def _write_only(self, request: bytes) -> None:
        """Send a setter and consume its ACK so it cannot pollute the next read."""
        if not self._transport.is_open:
            raise LitraDisconnectedError(f"{self.device_id} is not open")
        self._transport.drain()
        self._transport.write_report(request)
        # The ACK is not worth validating -- its parameters are zeroed -- but it
        # must be taken off the queue.
        self._transport.read_report(EXCHANGE_TIMEOUT_MS)

    # -- reads ------------------------------------------------------------

    def get_power(self) -> bool:
        with self._lock:
            report = self._exchange(self.protocol.encode_get_power(), FN_GET_POWER)
            value = self.protocol.decode_power(report)
            self._state.power = value
            return value

    def get_brightness(self) -> int:
        with self._lock:
            report = self._exchange(
                self.protocol.encode_get_brightness(), FN_GET_BRIGHTNESS
            )
            value = self.protocol.decode_brightness(report)
            self._state.brightness_lm = value
            return value

    def get_temperature(self) -> int:
        with self._lock:
            report = self._exchange(
                self.protocol.encode_get_temperature(), FN_GET_TEMPERATURE
            )
            value = self.protocol.decode_temperature(report)
            self._state.temperature_k = value
            return value

    def refresh(self) -> LitraState:
        """Read all three properties in one pass and return the new state."""
        self.get_power()
        self.get_brightness()
        self.get_temperature()
        return self.state

    # -- writes -----------------------------------------------------------

    def set_power(self, enabled: bool) -> None:
        with self._lock:
            self._write_only(self.protocol.encode_set_power(enabled))
            self._state.power = bool(enabled)

    def set_brightness(self, lumens: int) -> None:
        lumens = clamp_lumens(lumens)
        with self._lock:
            self._write_only(self.protocol.encode_set_brightness(lumens))
            self._state.brightness_lm = lumens

    def set_temperature(self, kelvin: int) -> None:
        kelvin = normalize_kelvin(kelvin)
        with self._lock:
            self._write_only(self.protocol.encode_set_temperature(kelvin))
            self._state.temperature_k = kelvin

    # -- identification ---------------------------------------------------

    def identify_frames(self) -> list[tuple[bool, float]]:
        """The flash pattern used to identify a light: (power, hold seconds).

        Returned rather than executed so the manager can sleep between frames
        without holding the device lock.
        """
        return [(False, 0.25), (True, 0.25), (False, 0.25), (True, 0.25)]

    def __repr__(self) -> str:
        return f"<LitraDevice {self.device_id} connected={self._state.connected}>"
