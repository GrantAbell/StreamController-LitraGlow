"""Litra Glow: Color Temperature.

Warmer means a lower Kelvin value and cooler a higher one, so the sign flips
between the user-facing wording and the value sent to the light. Clockwise
defaults to warmer and is reversible.
"""

from __future__ import annotations

from GtkHelper.ComboRow import SimpleComboRowItem
from GtkHelper.GenerativeUI.ComboRow import ComboRow
from GtkHelper.GenerativeUI.ScaleRow import ScaleRow
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..litra.models import MAX_KELVIN, MIN_KELVIN, GroupState
from ..litra.semantics import (
    CLOCKWISE_COOLER,
    CLOCKWISE_WARMER,
    KEY_MODE_COOLER,
    KEY_MODE_SET,
    KEY_MODE_WARMER,
    temperature_dial_delta,
    temperature_key_delta,
)
from ..rendering.temperature import render_temperature
from .base import LitraActionBase

DIAL_PRESS_TOGGLE_POWER = "toggle_power"
DIAL_PRESS_NOTHING = "nothing"

STEP_CHOICES = (100, 200, 500)


class TemperatureAction(LitraActionBase):
    TITLE = "Temp"
    EXTRA_DEFAULTS = {
        "key_mode": KEY_MODE_WARMER,
        "step_kelvin": 100,
        "fixed_kelvin": 4200,
        "dial_step_kelvin": 100,
        "clockwise_behavior": CLOCKWISE_WARMER,
        "dial_press_action": DIAL_PRESS_TOGGLE_POWER,
    }

    # -- settings UI ------------------------------------------------------

    def build_action_ui(self) -> None:
        step_items = [SimpleComboRowItem(str(k), f"{k} K") for k in STEP_CHOICES]

        self._key_mode_row = ComboRow(
            action_core=self,
            var_name="key_mode",
            default_value=KEY_MODE_WARMER,
            items=[
                SimpleComboRowItem(KEY_MODE_WARMER, "Warmer"),
                SimpleComboRowItem(KEY_MODE_COOLER, "Cooler"),
                SimpleComboRowItem(KEY_MODE_SET, "Set value"),
            ],
            title="Key press",
            subtitle="What a key press does",
        )
        self._step_row = ComboRow(
            action_core=self,
            var_name="step_kelvin",
            default_value="100",
            items=list(step_items),
            title="Key step",
            subtitle="Kelvin per key press",
        )
        self._fixed_row = ScaleRow(
            action_core=self,
            var_name="fixed_kelvin",
            default_value=4200,
            min=MIN_KELVIN,
            max=MAX_KELVIN,
            step=100,
            digits=0,
            title="Fixed temperature",
            subtitle="Used by Set value",
        )
        self._dial_step_row = ComboRow(
            action_core=self,
            var_name="dial_step_kelvin",
            default_value="100",
            items=[SimpleComboRowItem(str(k), f"{k} K") for k in STEP_CHOICES],
            title="Dial step",
            subtitle="Kelvin per dial tick",
        )
        self._clockwise_row = ComboRow(
            action_core=self,
            var_name="clockwise_behavior",
            default_value=CLOCKWISE_WARMER,
            items=[
                SimpleComboRowItem(CLOCKWISE_WARMER, "Warmer"),
                SimpleComboRowItem(CLOCKWISE_COOLER, "Cooler"),
            ],
            title="Clockwise",
            subtitle="Which way the dial goes when turned clockwise",
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
                id="litra_temperature_key",
                ui_label="Run temperature key action",
                default_events=[Input.Key.Events.DOWN],
                callback=self._on_key,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_temperature_cw",
                ui_label="Turn clockwise",
                default_events=[Input.Dial.Events.TURN_CW],
                callback=self._on_turn_cw,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_temperature_ccw",
                ui_label="Turn counter-clockwise",
                default_events=[Input.Dial.Events.TURN_CCW],
                callback=self._on_turn_ccw,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_temperature_dial_press",
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

        mode = self._combo_value("key_mode", KEY_MODE_WARMER)
        delta = temperature_key_delta(mode, self._step("step_kelvin", 100))

        if delta is None:
            self.manager.set_temperature(targets, self._step("fixed_kelvin", 4200))
            return

        self.manager.adjust_temperature(targets, delta)

    def _on_turn_cw(self, _data=None) -> None:
        self._turn(clockwise=True)

    def _on_turn_ccw(self, _data=None) -> None:
        self._turn(clockwise=False)

    def _turn(self, clockwise: bool) -> None:
        targets = self.get_targets()
        if not targets:
            return

        delta = temperature_dial_delta(
            clockwise,
            self._combo_value("clockwise_behavior", CLOCKWISE_WARMER),
            self._step("dial_step_kelvin", 100),
        )
        self.manager.adjust_temperature(targets, delta)

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
        return render_temperature(group, is_dial=self.is_dial)

    def state_signature(self, group: GroupState):
        return (
            group.device_count,
            group.any_connected,
            group.temperature_k,
            group.mixed_temperature,
        )
