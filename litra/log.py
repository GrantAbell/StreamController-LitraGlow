"""Logger for the device layer.

Uses StreamController's loguru logger when running inside the app, so Litra
messages land in the normal StreamController log where a user can find them, and
falls back to the standard library when the layer is imported on its own (tests,
probe_litra.py).

Because the two libraries interpolate differently -- loguru uses str.format,
logging uses %-style -- callers must pre-format their messages with f-strings.
"""

from __future__ import annotations

try:
    from loguru import logger as log
except ImportError:  # running outside StreamController
    import logging

    log = logging.getLogger("litra")

__all__ = ["log"]
