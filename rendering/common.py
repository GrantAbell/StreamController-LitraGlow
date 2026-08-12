"""Shared drawing helpers for key and dial images.

Pillow only -- no GTK, no device access. Renderers are pure functions of state,
which is what lets the actions redraw safely from any thread and lets the tests
assert on them without hardware.
"""

from __future__ import annotations

import glob
import math
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# Stream Deck keys are square; a Stream Deck+ dial owns a 200x100 slice of the
# touchscreen strip.
KEY_SIZE = (144, 144)
DIAL_SIZE = (200, 100)

BACKGROUND = (16, 17, 20)
TITLE_COLOR = (150, 155, 165)
VALUE_COLOR = (245, 246, 250)
MUTED_COLOR = (110, 115, 125)
TRACK_COLOR = (48, 51, 58)
ACCENT_ON = (255, 196, 92)
ACCENT_OFF = (90, 95, 105)
DISCONNECTED_COLOR = (226, 92, 84)
MIXED_COLOR = (156, 163, 255)

_FONT_CANDIDATES = (
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
)


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    # Last resort: any bold sans on the system.
    for pattern in ("/usr/share/fonts/**/*Bold.ttf", "/usr/share/fonts/**/*.ttf"):
        matches = glob.glob(pattern, recursive=True)
        if matches:
            return sorted(matches)[0]
    return None


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont:
    path = _font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, minimum: int = 10):
    """Shrink the font until the text fits, so long values never overflow."""
    size = start
    while size > minimum:
        font = _font(size)
        if _text_width(draw, text, font) <= max_width:
            return font
        size -= 2
    return _font(minimum)


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Approximate the visible colour of a temperature, for the accent bar.

    A rough Tanner Helland style approximation -- close enough that 2700 K reads
    as warm orange and 6500 K as cool white at a glance.
    """
    temperature = max(1000, min(40000, kelvin)) / 100.0

    if temperature <= 66:
        red = 255.0
    else:
        red = 329.698727446 * ((temperature - 60) ** -0.1332047592)

    if temperature <= 66:
        green = 99.4708025861 * _safe_log(temperature) - 161.1195681661
    else:
        green = 288.1221695283 * ((temperature - 60) ** -0.0755148492)

    if temperature >= 66:
        blue = 255.0
    elif temperature <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * _safe_log(temperature - 10) - 305.0447927307

    return (
        int(max(0, min(255, red))),
        int(max(0, min(255, green))),
        int(max(0, min(255, blue))),
    )


def _safe_log(value: float) -> float:
    return math.log(value) if value > 0 else 0.0


def new_canvas(size: tuple[int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", size, BACKGROUND + (255,))
    return image, ImageDraw.Draw(image)


def render_card(
    size: tuple[int, int],
    title: str,
    value: str,
    accent: tuple[int, int, int] = ACCENT_ON,
    fill: float | None = None,
    value_color: tuple[int, int, int] = VALUE_COLOR,
    disconnected: bool = False,
    subdued: bool = False,
) -> Image.Image:
    """Draw the standard two-line card used by every action.

    `fill` (0.0-1.0) draws a progress track, which is what makes a dial's
    position readable at a glance.
    """
    image, draw = new_canvas(size)
    width, height = size
    is_dial = width > height
    margin = max(8, width // 16)

    if disconnected:
        # A distinct outline so "unplugged" never looks like "off".
        draw.rectangle(
            [(1, 1), (width - 2, height - 2)],
            outline=DISCONNECTED_COLOR,
            width=max(2, width // 40),
        )

    # Lay out top-down into bands so the value can never collide with the title
    # or the bar, at either aspect ratio.
    title_font = _font(max(11, height // (7 if is_dial else 9)))
    title_text = title.upper()
    title_width = _text_width(draw, title_text, title_font)
    title_y = margin if is_dial else int(height * 0.14)
    _, title_top, _, title_bottom = draw.textbbox((0, 0), title_text, font=title_font)
    draw.text(
        ((width - title_width) / 2, title_y),
        title_text,
        font=title_font,
        fill=MUTED_COLOR if subdued else TITLE_COLOR,
    )

    bar_height = max(5, height // 14)
    bar_y = height - margin - bar_height

    band_top = title_y + (title_bottom - title_top) + max(4, height // 24)
    band_bottom = (bar_y - max(4, height // 24)) if fill is not None else (height - margin)

    value_font = _fit_font(
        draw,
        value,
        width - 2 * margin,
        start=max(18, int((band_bottom - band_top) * (1.0 if is_dial else 0.95))),
    )
    value_width = _text_width(draw, value, value_font)
    _, top, _, bottom = draw.textbbox((0, 0), value, font=value_font)
    value_y = band_top + ((band_bottom - band_top) - (bottom - top)) / 2 - top

    draw.text(
        ((width - value_width) / 2, value_y),
        value,
        font=value_font,
        fill=value_color,
    )

    if fill is not None:
        draw.rounded_rectangle(
            [(margin, bar_y), (width - margin, bar_y + bar_height)],
            radius=bar_height // 2,
            fill=TRACK_COLOR,
        )
        filled = max(0.0, min(1.0, fill))
        if filled > 0:
            end = margin + (width - 2 * margin) * filled
            end = max(end, margin + bar_height)
            draw.rounded_rectangle(
                [(margin, bar_y), (end, bar_y + bar_height)],
                radius=bar_height // 2,
                fill=accent,
            )

    return image


def size_for(is_dial: bool) -> tuple[int, int]:
    return DIAL_SIZE if is_dial else KEY_SIZE


def render_message(title: str, message: str, is_dial: bool = False) -> Image.Image:
    """A plain status card, used for conditions no value can express."""
    return render_card(
        size_for(is_dial),
        title,
        message,
        value_color=DISCONNECTED_COLOR,
        disconnected=True,
    )
