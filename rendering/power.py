"""Power key/dial rendering."""

from __future__ import annotations

from PIL import Image

from ..litra.models import GroupState

from .common import (
    ACCENT_OFF,
    ACCENT_ON,
    DISCONNECTED_COLOR,
    MIXED_COLOR,
    MUTED_COLOR,
    VALUE_COLOR,
    render_card,
    size_for,
)

TITLE = "Litra"


def render_power(group: GroupState, is_dial: bool = False) -> Image.Image:
    size = size_for(is_dial)

    if group.device_count == 0:
        return render_card(
            size, TITLE, "SET UP", value_color=MUTED_COLOR, subdued=True
        )

    if not group.any_connected:
        return render_card(
            size,
            TITLE,
            "N/C",
            value_color=DISCONNECTED_COLOR,
            disconnected=True,
        )

    if group.mixed_power:
        return render_card(size, TITLE, "MIXED", value_color=MIXED_COLOR)

    if group.power is None:
        return render_card(size, TITLE, "--", value_color=MUTED_COLOR)

    if group.power:
        return render_card(size, TITLE, "ON", accent=ACCENT_ON, value_color=ACCENT_ON)
    return render_card(size, TITLE, "OFF", accent=ACCENT_OFF, value_color=VALUE_COLOR)
