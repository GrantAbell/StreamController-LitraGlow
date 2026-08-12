"""Brightness key/dial rendering."""

from __future__ import annotations

from PIL import Image

from ..litra.models import GroupState

from .common import (
    ACCENT_ON,
    DISCONNECTED_COLOR,
    MIXED_COLOR,
    MUTED_COLOR,
    render_card,
    size_for,
)

TITLE = "Brightness"


def render_brightness(group: GroupState, is_dial: bool = False) -> Image.Image:
    size = size_for(is_dial)

    if group.device_count == 0:
        return render_card(size, TITLE, "SET UP", value_color=MUTED_COLOR, subdued=True)

    if not group.any_connected:
        return render_card(
            size, TITLE, "N/C", value_color=DISCONNECTED_COLOR, disconnected=True
        )

    if group.mixed_brightness:
        return render_card(size, TITLE, "MIXED", value_color=MIXED_COLOR)

    percent = group.brightness_percent
    if percent is None:
        return render_card(size, TITLE, "--", value_color=MUTED_COLOR)

    # The bar tracks brightness even when the light is off, so the dial still
    # shows where it is set; the dimmed accent conveys the off state.
    accent = ACCENT_ON if group.power is not False else (120, 100, 70)
    return render_card(
        size,
        TITLE,
        f"{percent}%",
        accent=accent,
        fill=percent / 100.0,
    )
