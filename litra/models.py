"""Data models and the device's value ranges.

These constants live here, not in the actions, so that the ranges and the
percent/lumen mapping are defined exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

VENDOR_ID = 0x046D
PRODUCT_ID = 0xC900

# Litra Glow's supported ranges.
MIN_LUMENS = 20
MAX_LUMENS = 250
MIN_KELVIN = 2700
MAX_KELVIN = 6500
KELVIN_STEP = 100

# Sentinel target meaning "every connected Litra Glow, including ones that
# connect later".
TARGET_MODE_ALL = "all"
TARGET_MODE_SELECTED = "selected"


@dataclass(frozen=True)
class LitraDeviceInfo:
    """Identity of one physical light.

    `device_id` is the persistent handle used in action settings: the serial
    number when the device exposes one, otherwise the HID path.
    Discovery order is never used as an identity.
    """

    device_id: str
    serial_number: str | None
    path: bytes
    vendor_id: int
    product_id: int

    @property
    def path_str(self) -> str:
        return self.path.decode("utf-8", errors="replace")

    @property
    def display_name(self) -> str:
        if self.serial_number:
            return f"Litra Glow ({self.serial_number})"
        return f"Litra Glow ({self.path_str})"


@dataclass
class LitraState:
    """Last known state of one light. `None` means "not yet known"."""

    connected: bool = False
    power: bool | None = None
    brightness_lm: int | None = None
    temperature_k: int | None = None

    def copy(self) -> "LitraState":
        return LitraState(
            connected=self.connected,
            power=self.power,
            brightness_lm=self.brightness_lm,
            temperature_k=self.temperature_k,
        )

    @property
    def brightness_percent(self) -> int | None:
        if self.brightness_lm is None:
            return None
        return lumens_to_percent(self.brightness_lm)


@dataclass
class GroupState:
    """Aggregate of several lights, for rendering a single key or dial.

    `mixed_*` is True when the connected members disagree, which the UI renders
    as MIXED rather than picking an arbitrary member's value.
    """

    any_connected: bool = False
    all_connected: bool = False
    power: bool | None = None
    brightness_lm: int | None = None
    temperature_k: int | None = None
    mixed_power: bool = False
    mixed_brightness: bool = False
    mixed_temperature: bool = False
    device_count: int = 0
    connected_count: int = 0
    states: dict[str, LitraState] = field(default_factory=dict)

    @property
    def brightness_percent(self) -> int | None:
        if self.brightness_lm is None:
            return None
        return lumens_to_percent(self.brightness_lm)


# --------------------------------------------------------------------------
# Value mapping helpers
# --------------------------------------------------------------------------


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def clamp_lumens(lumens: int) -> int:
    return clamp(int(round(lumens)), MIN_LUMENS, MAX_LUMENS)


def percent_to_lumens(percent: float) -> int:
    """Map a user-facing 0-100% onto the device's 20-250 lm range.

    0% is the dimmest the light goes, not off; powering off is a separate
    operation.
    """
    percent = max(0.0, min(100.0, float(percent)))
    lumens = MIN_LUMENS + (percent / 100.0) * (MAX_LUMENS - MIN_LUMENS)
    return clamp_lumens(round(lumens))


def lumens_to_percent(lumens: int) -> int:
    """Inverse of percent_to_lumens, clamped to 0-100."""
    percent = (lumens - MIN_LUMENS) / (MAX_LUMENS - MIN_LUMENS) * 100.0
    return int(clamp(int(round(percent)), 0, 100))


def normalize_kelvin(kelvin: int) -> int:
    """Snap to a valid 100 K step inside the supported range."""
    stepped = int(round(float(kelvin) / KELVIN_STEP)) * KELVIN_STEP
    return clamp(stepped, MIN_KELVIN, MAX_KELVIN)
