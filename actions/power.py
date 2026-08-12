"""Litra Glow: Power.

Key press and dial press both run the configured operation; rotation does
nothing. Toggle is evaluated across the whole group, so a mixed group resolves
to a single sensible outcome instead of each light merely inverting.
"""

from __future__ import annotations

from GtkHelper.ComboRow import SimpleComboRowItem
from GtkHelper.GenerativeUI.ComboRow import ComboRow
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..litra.models import GroupState
from ..rendering.power import render_power
from .base import LitraActionBase

OPERATION_TOGGLE = "toggle"
OPERATION_ON = "on"
OPERATION_OFF = "off"


class PowerAction(LitraActionBase):
    TITLE = "Litra"
    EXTRA_DEFAULTS = {"operation": OPERATION_TOGGLE}

    # -- settings UI ------------------------------------------------------

    def build_action_ui(self) -> None:
        self._operation_row = ComboRow(
            action_core=self,
            var_name="operation",
            default_value=OPERATION_TOGGLE,
            items=[
                SimpleComboRowItem(OPERATION_TOGGLE, "Toggle"),
                SimpleComboRowItem(OPERATION_ON, "On"),
                SimpleComboRowItem(OPERATION_OFF, "Off"),
            ],
            title="Operation",
            subtitle="What a press does",
        )

    # -- events -----------------------------------------------------------

    def register_events(self) -> None:
        self.add_event_assigner(
            EventAssigner(
                id="litra_power_key",
                ui_label="Run power operation",
                default_events=[Input.Key.Events.DOWN],
                callback=self._on_pressed,
            )
        )
        self.add_event_assigner(
            EventAssigner(
                id="litra_power_dial",
                ui_label="Run power operation (dial press)",
                default_events=[Input.Dial.Events.DOWN],
                callback=self._on_pressed,
            )
        )

    def _on_pressed(self, _data=None) -> None:
        targets = self.get_targets()
        if not targets:
            return

        operation = self._combo_value("operation", OPERATION_TOGGLE)
        if operation == OPERATION_ON:
            self.manager.set_power(targets, True)
        elif operation == OPERATION_OFF:
            self.manager.set_power(targets, False)
        else:
            self.manager.toggle_power(targets)

    # -- rendering --------------------------------------------------------

    def render_image(self, group: GroupState):
        return render_power(group, is_dial=self.is_dial)

    def state_signature(self, group: GroupState):
        return (group.device_count, group.any_connected, group.power, group.mixed_power)
