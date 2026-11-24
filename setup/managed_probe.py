"""GUI-free health probe for staged SmoothCast generations (#580).

``managed_activation.verify_release`` hash-verifies a staged generation's
files before the probe runs; this probe answers a different question: can the
runtime run the staged generation right now? It reuses the installer's
GUI-free checks (Python 3.10+, GTK4/libadwaita bindings, cast dependencies,
media executables) and starts no GUI, window, network service or media file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bootstrap

APP_ENTRY = "src/cast_control.py"
VENV_PYTHONS = (".venv/bin/python", ".venv/bin/python3", ".venv/Scripts/python.exe")


def default_probe(generation: Path) -> bool:
    """Return True only when the runtime satisfies the staged generation."""
    generation = Path(generation)
    if not (generation / APP_ENTRY).is_file():
        return False
    python = next((generation / part for part in VENV_PYTHONS
                   if (generation / part).is_file()), Path(sys.executable))
    if not bootstrap.python_ok(python):
        return False
    if not bootstrap.works(python, bootstrap.GUI_CHECK):
        return False
    if not bootstrap.works(python, bootstrap.CAST_DEPENDENCIES_CHECK):
        return False
    return not bootstrap.check_tools()
