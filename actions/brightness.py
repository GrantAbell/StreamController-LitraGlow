"""Litra Glow: Brightness.

Brightness is user-facing as a percentage; the lumen mapping lives in
litra.models so the action never deals in raw device units.

Increase/Decrease are relative and applied per light, so a group keeps its
per-light offsets. Set Value is absolute and deliberately makes every target
match.
"""

from __future__ import annotations

from GtkHelper.ComboRow import SimpleComboRowItem
from GtkHelper.GenerativeUI.ComboRow import ComboRow
from GtkHelper.GenerativeUI.ScaleRow import ScaleRow
from GtkHelper.GenerativeUI.SpinRow import SpinRow
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..litra.models import GroupState
from ..litra.semantics import (
    KEY_MODE_DECREASE,
    KEY_MODE_INCREASE,
    KEY_MODE_SET,
    brightness_dial_delta,
    brightness_key_delta,
)
from ..rendering.brightness import render_brightness
from .base import LitraActionBase

DIAL_PRESS_TOGGLE_POWER = "toggle_power"
DIAL_PRESS_NOTHING = "nothing"


class BrightnessAction(LitraActionBase):
    TITLE = "Brightness"
    EXTRA_DEFAULTS = {
        "key_mode": KEY_MODE_INCREASE,
        "step_percent": 5,
        "fixed_percent": 60,
        "dial_step_percent": 5,
        "dial_press_action": DIAL_PRESS_TOGGLE_POWER,
    }

    # -- settings UI ------------------------------------------------------

    def build_action_ui(self) -> None:
        self._key_mode_row = ComboRow(
            action_core=self,
            var_name="key_mode",
            default_value=KEY_MODE_INCREASE,
            items=[
                SimpleComboRowItem(KEY_MODE_INCREASE, "Increase"),
                SimpleComboRowItem(KEY_MODE_DECREASE, "Decrease"),
                SimpleComboRowItem(KEY_MODE_SET, "Set value"),
            ],
            title="Key press",
            subtitle="What a key press does",
        )
        self._step_row = SpinRow(
            action_core=self,
            var_name="step_percent",
            default_value=5,
            min=1,
            max=50,
            step=1,
            digits=0,
            title="Key step",
            subtitle="Percentage points per key press",
        )
        self._fixed_row = ScaleRow(
            action_core=self,
            var_name="fixed_percent",
            default_value=60,
            min=0,
            max=100,
            step=1,
            digits=0,
            title="Fixed brightness",
            subtitle="Used by Set value. 0% is the dimmest setting, not off.",
        )
        self._dial_step_row = SpinRow(
            action_core=self,
            var_name="dial_step_percent",
            default_value=5,
            min=1,
            max=25,
            step=1,
            digits=0,
            title="Dial step",
            subtitle="Percentage points per dial tick",
        )
        self._dial_press_row = ComboRow(
            action_core=self,
            var_name="dial_press_action",
            default_value=DIAL_PRESS_TOGGLE_POWER,
            items=[
                SimpleComboRowItem(DIAL_PRESS_TOGGLE_POWER, "Toggle power"),
                SimpleComboRowItem(DIAL_PRESS_NOTHING, "Nothing"),
            ],
            title="Dial press",
            subtitle="What pressing the dial does",
        )

    # -- events -----------------------------------------------------------

    def register_events(self) -> None:
        self.add_event_assigner(
            EventAssigner(
                id="litra_brightness_key",
                ui_label="Run brightness key action",
                default_events=[Input.Key.Events.DOWN],
                callback=self._on_key,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_brightness_cw",
                ui_label="Brightness up",
                default_events=[Input.Dial.Events.TURN_CW],
                callback=self._on_turn_cw,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_brightness_ccw",
                ui_label="Brightness down",
                default_events=[Input.Dial.Events.TURN_CCW],
                callback=self._on_turn_ccw,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_brightness_dial_press",
                ui_label="Dial press",
                default_events=[Input.Dial.Events.DOWN],
                callback=self._on_dial_press,
            )
        )

    def _step(self, key: str, fallback: int) -> int:
        try:
            return max(1, int(round(float(self.setting(key, fallback)))))
        except (TypeError, ValueError):
            return fallback

    def _on_key(self, _data=None) -> None:
        targets = self.get_targets()
        if not targets:
            return

        mode = self._combo_value("key_mode", KEY_MODE_INCREASE)
        delta = brightness_key_delta(mode, self._step("step_percent", 5))

        if delta is None:
            try:
                percent = float(self.setting("fixed_percent", 60))
            except (TypeError, ValueError):
                percent = 60.0
            self.manager.set_brightness_percent(targets, percent)
            return

        self.manager.adjust_brightness_percent(targets, delta)

    # StreamController supplies no tick count with a turn event, so each event
    # is exactly one step (verified in DeckController).
    def _on_turn_cw(self, _data=None) -> None:
        self._turn(clockwise=True)

    def _on_turn_ccw(self, _data=None) -> None:
        self._turn(clockwise=False)

    def _turn(self, clockwise: bool) -> None:
        targets = self.get_targets()
        if not targets:
            return
        delta = brightness_dial_delta(clockwise, self._step("dial_step_percent", 5))
        self.manager.adjust_brightness_percent(targets, delta)

    def _on_dial_press(self, _data=None) -> None:
        if self._combo_value("dial_press_action", DIAL_PRESS_TOGGLE_POWER) != (
            DIAL_PRESS_TOGGLE_POWER
        ):
            return
        targets = self.get_targets()
        if targets:
            self.manager.toggle_power(targets)

    # -- rendering --------------------------------------------------------

    def render_image(self, group: GroupState):
        return render_brightness(group, is_dial=self.is_dial)

    def state_signature(self, group: GroupState):
        return (
            group.device_count,
            group.any_connected,
            group.brightness_percent,
            group.mixed_brightness,
            group.power,
        )
