"""Exception hierarchy for the Litra layer.

HID-library and OS exceptions are converted to these at the transport/manager
boundary so that a device error never propagates uncaught into StreamController.
"""

from __future__ import annotations


class LitraError(Exception):
    """Base class for every error raised by this plugin's device layer."""


class LitraNotFoundError(LitraError):
    """No supported Litra device is present."""


class LitraPermissionError(LitraError):
    """A Litra device was found but could not be opened due to permissions.

    Distinct from LitraNotFoundError so the UI can tell the user to install the
    udev rule rather than to plug the light in.
    """


class LitraDisconnectedError(LitraError):
    """The device vanished, or an operation failed because it is gone."""


class LitraProtocolError(LitraError):
    """A HID++ report was malformed, truncated, or out of range."""


class LitraHidError(LitraError):
    """A low-level HID I/O failure that is not one of the above."""
