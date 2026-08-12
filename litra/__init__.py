"""Device layer for the Litra Glow plugin.

Layering, strictly one direction:

    action -> LitraDeviceManager -> LitraDevice -> LitraProtocol / LitraTransport

Nothing above the transport performs HID I/O; nothing below the manager knows
that StreamController exists.
"""

from .errors import (
    LitraDisconnectedError,
    LitraError,
    LitraHidError,
    LitraNotFoundError,
    LitraPermissionError,
    LitraProtocolError,
)
from .manager import LitraDeviceManager
from .models import (
    MAX_KELVIN,
    MAX_LUMENS,
    MIN_KELVIN,
    MIN_LUMENS,
    TARGET_MODE_ALL,
    TARGET_MODE_SELECTED,
    GroupState,
    LitraDeviceInfo,
    LitraState,
    lumens_to_percent,
    normalize_kelvin,
    percent_to_lumens,
)

__all__ = [
    "GroupState",
    "LitraDeviceInfo",
    "LitraDeviceManager",
    "LitraDisconnectedError",
    "LitraError",
    "LitraHidError",
    "LitraNotFoundError",
    "LitraPermissionError",
    "LitraProtocolError",
    "LitraState",
    "MAX_KELVIN",
    "MAX_LUMENS",
    "MIN_KELVIN",
    "MIN_LUMENS",
    "TARGET_MODE_ALL",
    "TARGET_MODE_SELECTED",
    "lumens_to_percent",
    "normalize_kelvin",
    "percent_to_lumens",
]
