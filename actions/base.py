"""Shared behaviour for every Litra action.

Handles the parts that are identical across Power, Brightness and Temperature:
settings defaults and migration, device targeting, the device-selection UI with
Identify, the StreamController lifecycle, and redrawing from manager
notifications.

Subclasses supply their own inputs, their own extra settings rows, and their own
renderer. None of them may touch HID -- everything goes through the manager.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from loguru import logger as log

from GtkHelper.ComboRow import SimpleComboRowItem
from GtkHelper.GenerativeUI.ComboRow import ComboRow
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore

from ..litra.models import TARGET_MODE_ALL, TARGET_MODE_SELECTED, GroupState
from ..rendering.common import render_message

SCHEMA_VERSION = 1


class LitraActionBase(ActionCore):
    #: Shown as the small caption on the key or dial.
    TITLE = "Litra"

    #: Extra settings keys and their defaults, merged with the shared ones.
    EXTRA_DEFAULTS: dict = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

        self._watched: list[str] = []
        self._last_signature = None
        self._device_rows_group: Adw.PreferencesGroup | None = None
        self._device_rows: list = []
        self._listener_registered = False

        # Settings are NOT written here. StreamController only registers the
        # action in page.action_objects after every action on the page has been
        # constructed, so set_settings() during __init__ raises KeyError.
        # Reads merge defaults instead, and the migration write happens in
        # on_ready().
        self._build_target_ui()
        self.build_action_ui()
        self.register_events()

    # -- plumbing ---------------------------------------------------------

    @property
    def manager(self):
        return self.plugin_base.litra

    @property
    def is_dial(self) -> bool:
        return isinstance(self.input_ident, Input.Dial)

    def settings(self) -> dict:
        """Stored settings with defaults filled in.

        Reads never depend on a previous write having succeeded, so an action
        works correctly from the moment it is constructed -- before
        StreamController will accept set_settings() at all.
        """
        merged = self._defaults()
        merged.update(self.get_settings() or {})
        return merged

    def setting(self, key: str, fallback=None):
        return self.settings().get(key, fallback)

    def _defaults(self) -> dict:
        defaults = {
            "schema_version": SCHEMA_VERSION,
            "target_mode": TARGET_MODE_SELECTED,
            "device_ids": [],
        }
        defaults.update(self.EXTRA_DEFAULTS)
        return defaults

    def _persist_settings(self) -> None:
        """Write the merged settings back once, so the page file is explicit.

        Must not be called before on_ready: see the note in __init__.
        Behaviour does not depend on this succeeding -- settings() already
        merges defaults -- so a failure is logged and ignored.

        schema_version is stored so a future settings change can be migrated
        rather than silently misread.
        """
        stored = self.get_settings() or {}
        merged = self.settings()
        merged["schema_version"] = SCHEMA_VERSION

        if merged == stored:
            return

        try:
            self.set_settings(merged)
        except Exception:
            log.exception(f"Litra: could not persist settings for {self.action_id}")

    # -- targeting --------------------------------------------------------

    def get_targets(self) -> list[str]:
        """Device IDs this action currently acts on."""
        settings = self.settings()
        return self.manager.resolve_targets(
            settings.get("target_mode", TARGET_MODE_SELECTED),
            settings.get("device_ids", []),
        )

    def get_group(self) -> GroupState:
        settings = self.settings()
        return self.manager.get_group_state(
            settings.get("target_mode", TARGET_MODE_SELECTED),
            settings.get("device_ids", []),
        )

    def _update_watch(self) -> None:
        """Tell the manager which devices this action needs polled."""
        settings = self.settings()
        if settings.get("target_mode") == TARGET_MODE_ALL:
            wanted = [TARGET_MODE_ALL]
        else:
            wanted = list(settings.get("device_ids", []))

        if wanted == self._watched:
            return
        if self._watched:
            self.manager.unwatch(self._watched)
        self.manager.watch(wanted)
        self._watched = wanted

    # -- lifecycle --------------------------------------------------------

    def on_ready(self) -> None:
        # Safe here: the action is registered on its page by this point.
        self._persist_settings()

        if not self._listener_registered:
            self.manager.add_listener(self._on_state_changed)
            self._listener_registered = True
        self._update_watch()
        # Force a redraw even if the cached state is unchanged, because the key
        # image itself was reset when the page was loaded.
        self._last_signature = None
        self.render()
        self.manager.refresh_now(self.get_targets())

    def on_update(self) -> None:
        self._update_watch()
        self._last_signature = None
        self.render()

    def on_remove(self) -> None:
        self._teardown()

    def on_removed_from_cache(self) -> None:
        self._teardown()

    def _teardown(self) -> None:
        """Drop every reference the manager holds to this action.

        Called on both remove paths so a page change cannot leak listeners or
        leave devices being polled for nobody.
        """
        if self._listener_registered:
            self.manager.remove_listener(self._on_state_changed)
            self._listener_registered = False
        if self._watched:
            self.manager.unwatch(self._watched)
            self._watched = []

    # -- rendering --------------------------------------------------------

    def _on_state_changed(self) -> None:
        self.render()

    def render_image(self, group: GroupState):
        """Subclass hook: return a Pillow image for this state."""
        raise NotImplementedError

    def state_signature(self, group: GroupState):
        """Subclass hook: what makes the drawn image different.

        Redrawing is skipped when this is unchanged, so the ~1 s state poll does
        not repaint the deck continuously.
        """
        raise NotImplementedError

    def render(self) -> None:
        if not self.on_ready_called:
            return

        try:
            group = self.get_group()
            permission_error = self.manager.permission_error

            signature = (
                self.state_signature(group),
                bool(permission_error) and not group.any_connected,
            )
            if signature == self._last_signature:
                return
            self._last_signature = signature

            if permission_error and not group.any_connected:
                # A light is present but cannot be opened -- a different problem
                # from no light at all.
                image = render_message(self.TITLE, "PERMS", is_dial=self.is_dial)
            else:
                image = self.render_image(group)

            self.set_media(image=image)
        except Warning:
            # set_media raises this if the action is not ready yet.
            pass
        except Exception:
            log.exception("Litra: failed to render %s", self.action_id)

    # -- events -----------------------------------------------------------

    def register_events(self) -> None:
        """Subclass hook: add EventAssigners."""

    # -- settings UI ------------------------------------------------------

    def _build_target_ui(self) -> None:
        self._target_mode_row = ComboRow(
            action_core=self,
            var_name="target_mode",
            default_value=TARGET_MODE_SELECTED,
            items=[
                SimpleComboRowItem(TARGET_MODE_SELECTED, "Selected lights"),
                SimpleComboRowItem(TARGET_MODE_ALL, "All connected lights"),
            ],
            title="Lights",
            subtitle="Which Litra Glow devices this action controls",
            on_change=self._on_target_mode_changed,
        )

    def build_action_ui(self) -> None:
        """Subclass hook: create the action's own Generative UI rows."""

    def _on_target_mode_changed(self, _widget, new_value, _old_value) -> None:
        self._refresh_device_rows()
        self._update_watch()
        self._last_signature = None
        self.render()

    def get_config_rows(self) -> list:
        # Rebuilt each time the configurator opens so newly plugged lights show
        # up without restarting StreamController.
        self._device_rows_group = Adw.PreferencesGroup(
            title="Litra Glow devices",
            description="Selected lights are remembered by serial number.",
        )
        self._refresh_device_rows()
        return [self._device_rows_group]

    def _refresh_device_rows(self) -> None:
        group = self._device_rows_group
        if group is None:
            return

        for row in getattr(self, "_device_rows", []):
            group.remove(row)
        self._device_rows = []

        settings = self.settings()
        selected: list[str] = list(settings.get("device_ids", []))
        target_all = settings.get("target_mode") == TARGET_MODE_ALL

        connected = {info.device_id: info for info in self.manager.get_devices()}

        # Show configured-but-absent lights too, so unplugging one does not make
        # the selection appear to vanish.
        ordered: list[tuple[str, str, bool]] = []
        for device_id, info in connected.items():
            ordered.append((device_id, info.display_name, True))
        for device_id in selected:
            if device_id not in connected:
                ordered.append((device_id, f"Litra Glow ({device_id})", False))

        if not ordered:
            row = Adw.ActionRow(
                title="No Litra Glow detected",
                subtitle=self.manager.permission_error
                or "Connect a Litra Glow over USB. It is detected automatically.",
            )
            group.add(row)
            self._device_rows.append(row)
            self._add_rescan_row(group)
            return

        for device_id, label, is_connected in ordered:
            row = Adw.ActionRow(
                title=label,
                subtitle="Connected" if is_connected else "Not connected",
            )

            switch = Gtk.Switch(
                active=device_id in selected,
                valign=Gtk.Align.CENTER,
                sensitive=not target_all,
                tooltip_text="Control this light with this action",
            )
            switch.connect("state-set", self._on_device_toggled, device_id)
            row.add_suffix(switch)

            identify = Gtk.Button(
                label="Identify",
                valign=Gtk.Align.CENTER,
                sensitive=is_connected,
                tooltip_text="Flash this light, then restore its previous state",
            )
            identify.connect("clicked", self._on_identify_clicked, device_id)
            row.add_suffix(identify)

            group.add(row)
            self._device_rows.append(row)

        self._add_rescan_row(group)

    def _add_rescan_row(self, group: Adw.PreferencesGroup) -> None:
        row = Adw.ActionRow(
            title="Rescan",
            subtitle="Lights are detected automatically; use this to refresh the list now.",
        )
        button = Gtk.Button(label="Rescan", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _b: self._refresh_device_rows())
        row.add_suffix(button)
        group.add(row)
        self._device_rows.append(row)

    def _on_device_toggled(self, _switch, active: bool, device_id: str) -> bool:
        settings = self.settings()
        selected = list(settings.get("device_ids", []))

        if active and device_id not in selected:
            selected.append(device_id)
        elif not active and device_id in selected:
            selected.remove(device_id)

        settings["device_ids"] = selected
        self.set_settings(settings)

        self._update_watch()
        self._last_signature = None
        self.render()
        self.manager.refresh_now(self.get_targets())
        return False

    def _on_identify_clicked(self, _button, device_id: str) -> None:
        # Returns immediately; the flash runs on the manager's worker thread.
        self.manager.identify(device_id)

    # -- helpers for subclasses -------------------------------------------

    def _combo_value(self, key: str, fallback: str) -> str:
        """Read a ComboRow-backed setting, tolerating either storage shape."""
        value = self.setting(key, fallback)
        if isinstance(value, SimpleComboRowItem):
            return value.get_value()
        if value is None:
            return fallback
        return str(value)
