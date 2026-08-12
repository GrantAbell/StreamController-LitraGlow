"""Colour-temperature key/dial rendering."""

from __future__ import annotations

from PIL import Image

from ..litra.models import MAX_KELVIN, MIN_KELVIN, GroupState

from .common import (
    DISCONNECTED_COLOR,
    MIXED_COLOR,
    MUTED_COLOR,
    kelvin_to_rgb,
    render_card,
    size_for,
)

TITLE = "Temp"


def render_temperature(group: GroupState, is_dial: bool = False) -> Image.Image:
    size = size_for(is_dial)

    if group.device_count == 0:
        return render_card(size, TITLE, "SET UP", value_color=MUTED_COLOR, subdued=True)

    if not group.any_connected:
        return render_card(
            size, TITLE, "N/C", value_color=DISCONNECTED_COLOR, disconnected=True
        )

    if group.mixed_temperature:
        return render_card(size, TITLE, "MIXED", value_color=MIXED_COLOR)

    kelvin = group.temperature_k
    if kelvin is None:
        return render_card(size, TITLE, "--", value_color=MUTED_COLOR)

    fill = (kelvin - MIN_KELVIN) / (MAX_KELVIN - MIN_KELVIN)
    return render_card(
        size,
        TITLE,
        f"{kelvin} K",
        # Tinting the bar with the actual light colour makes warm/cool obvious
        # without reading the number.
        accent=kelvin_to_rgb(kelvin),
        fill=max(0.0, min(1.0, fill)),
    )
