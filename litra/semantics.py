"""Pure decision rules shared by the actions.

These live outside actions/ because the action modules import GTK and
StreamController, which makes them unimportable in a test process. Keeping the
rules here means the trickiest behaviour -- warmer vs cooler, reversed
dial direction, increase vs decrease -- is directly testable.
"""

from __future__ import annotations

KEY_MODE_INCREASE = "increase"
KEY_MODE_DECREASE = "decrease"
KEY_MODE_WARMER = "warmer"
KEY_MODE_COOLER = "cooler"
KEY_MODE_SET = "set"

CLOCKWISE_WARMER = "warmer"
CLOCKWISE_COOLER = "cooler"


def brightness_key_delta(mode: str, step: int) -> int | None:
    """Percentage-point change for a brightness key press.

    None means the press is absolute (Set value) rather than relative.
    """
    if mode == KEY_MODE_SET:
        return None
    step = abs(int(step))
    return step if mode == KEY_MODE_INCREASE else -step


def brightness_dial_delta(clockwise: bool, step: int) -> int:
    """Clockwise brightens."""
    step = abs(int(step))
    return step if clockwise else -step


def temperature_key_delta(mode: str, step: int) -> int | None:
    """Kelvin change for a temperature key press.

    Warmer is a *lower* Kelvin value, so 'warmer' yields a negative delta.
    """
    if mode == KEY_MODE_SET:
        return None
    step = abs(int(step))
    return -step if mode == KEY_MODE_WARMER else step


def temperature_dial_delta(clockwise: bool, clockwise_behavior: str, step: int) -> int:
    """Kelvin change for one dial tick, honouring the reversal setting.

    clockwise_behavior says what a clockwise turn should do; counter-clockwise
    is its opposite. Warmer then maps to a negative Kelvin delta.
    """
    step = abs(int(step))
    warmer = clockwise_behavior == CLOCKWISE_WARMER
    if not clockwise:
        warmer = not warmer
    return -step if warmer else step


def group_toggle_target(power_states: list[bool | None]) -> bool:
    """What a group Toggle should set every target to.

    All known-on -> off; anything else (all off, mixed, nothing known) -> on.
    This stops a mixed group from merely inverting and staying mixed.
    """
    known = [state for state in power_states if state is not None]
    all_on = bool(known) and all(known)
    return not all_on
