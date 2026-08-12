# Litra Glow for StreamController

Control one or more USB-connected Logitech Litra Glow lights from
[StreamController](https://github.com/StreamController/StreamController), on
both Stream Deck keys and Stream Deck+ dials.

> **Disclaimer:** This plugin was built with the assistance of AI tools. Review
> the code yourself before relying on it, and please open an issue if you spot
> a bug or a mistake.

## Actions

| Action | Key | Dial |
| --- | --- | --- |
| **Litra Glow: Power** | Toggle / On / Off | Press runs the same operation; rotation does nothing |
| **Litra Glow: Brightness** | Increase / Decrease / Set value | Turn to dim and brighten, press to toggle power |
| **Litra Glow: Color Temperature** | Warmer / Cooler / Set value | Turn to warm and cool, press to toggle power |

Every action can target one light, several lights, or **all connected lights**,
including lights plugged in later.

## Features

- Lights are remembered by **serial number**, so a replug or a different USB
  port keeps your configuration working.
- **Identify** flashes a chosen light and then restores exactly what it was
  doing — useful when several lights are connected.
- Keys and dials show live state: power, brightness percentage, temperature in
  Kelvin, `MIXED` for a group that disagrees, and a distinct `N/C` for a light
  that is unplugged.
- Changes made with the light's own buttons are picked up within about a second.
- Relative changes across several lights **preserve each light's offset** — two
  lights 20% apart stay 20% apart.
- All USB work happens on a background worker, so nothing blocks
  StreamController's UI or input handling, and a fast dial spin still lands on
  the value you stopped at.
- Unplug and replug are handled automatically; no restart needed.
- **No third-party Python dependencies.** The plugin talks to `/dev/hidraw`
  through the standard library, which is what makes it work unchanged inside the
  StreamController Flatpak.

## Requirements

- A Logitech Litra Glow (USB `046D:C900`)
- Linux, with hidraw access to the light

## Installing

Clone into StreamController's plugin directory:

```bash
git clone https://github.com/GrantAbell/StreamController-LitraGlow \
  ~/.var/app/com.core447.StreamController/data/plugins/com_grant_LitraGlow
```

Then restart StreamController.

## Permissions

StreamController does **not** need to run as root. Your user needs read/write
access to the light's hidraw node. Check whether you already have it:

```bash
# find the node
for n in /sys/class/hidraw/hidraw*; do
  grep -q C900 "$n/device/uevent" && echo "/dev/$(basename "$n")"
done

# check access
getfacl -p /dev/hidrawN
```

If you do not see a `user:<you>:rw-` line, install the bundled rule:

```bash
sudo cp udev/99-litra-glow.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
```

Then unplug and replug the light. The rule uses `TAG+="uaccess"`, which grants
access to the logged-in user rather than to everyone on the machine.

If a light is detected but cannot be opened, the key shows `PERMS` rather than
`N/C`, so a permissions problem is distinguishable from an unplugged light.

## Verifying the hardware

`probe_litra.py` exercises all six device operations end to end and restores the
light's original state:

```bash
python3 probe_litra.py
# or, in the environment StreamController actually uses:
flatpak run --command=python3 com.core447.StreamController probe_litra.py
```

## Development

```bash
python3 -m pytest tests/ -q
```

The tests run against a fake transport that reproduces the real device's wire
behaviour, so no hardware is needed.

## License

GPL-3.0-or-later.
