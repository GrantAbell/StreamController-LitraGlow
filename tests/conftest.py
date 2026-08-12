"""Make the plugin importable as a package outside StreamController.

StreamController imports the plugin as `plugins.<plugin_id>`, so every internal
import is relative and the package must be loaded under *some* valid name. The
repository directory name contains a hyphen, so it is loaded here under the
alias `litra_glow` instead.

Only the device layer is imported by the tests; actions/ and main.py pull in GTK
and StreamController and cannot be imported in a bare test process. The rules
those actions depend on live in litra/semantics.py precisely so they can be
tested here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "litra_glow"

if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
