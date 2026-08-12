"""Litra Glow plugin entry point.

Owns exactly one LitraDeviceManager for the whole plugin; every action talks to
that one instance and none of them ever opens a device themselves.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from loguru import logger as log

import globals as gl
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase
from src.Signals import Signals

from .actions.brightness import BrightnessAction
from .actions.power import PowerAction
from .actions.temperature import TemperatureAction
from .litra.manager import LitraDeviceManager


class LitraGlowPlugin(PluginBase):
    def __init__(self):
        super().__init__()

        # The single hardware owner. Threads start here and stop on app quit.
        self.litra = LitraDeviceManager()
        self.litra.start()
        gl.signal_manager.connect_signal(Signals.AppQuit, self._on_quit)

        support = {
            Input.Key: ActionInputSupport.SUPPORTED,
            Input.Dial: ActionInputSupport.SUPPORTED,
            Input.Touchscreen: ActionInputSupport.UNSUPPORTED,
        }

        for suffix, action_core, name in (
            ("Power", PowerAction, "Litra Glow: Power"),
            ("Brightness", BrightnessAction, "Litra Glow: Brightness"),
            ("Temperature", TemperatureAction, "Litra Glow: Color Temperature"),
        ):
            self.add_action_holder(
                ActionHolder(
                    plugin_base=self,
                    action_core=action_core,
                    action_id_suffix=suffix,
                    action_name=name,
                    action_support=support,
                    icon=Gtk.Image(icon_name="weather-clear-symbolic"),
                )
            )

        self.register(
            plugin_name="Litra Glow",
            github_repo="https://github.com/GrantAbell/StreamController-LitraGlow",
            plugin_version="1.0.0",
            app_version="1.5.0-beta.15",
        )

        log.info(
            f"Litra Glow: registered {len(self.action_holders)} actions "
            f"(registered={self.registered})"
        )

    def _on_quit(self, *args, **kwargs):
        log.info("Litra Glow: shutting down device manager")
        try:
            self.litra.stop()
        except Exception:
            log.exception("Litra Glow: error while stopping device manager")

    def on_uninstall(self) -> None:
        self._on_quit()
        super().on_uninstall()
