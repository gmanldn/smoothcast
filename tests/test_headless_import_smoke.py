"""Headless smoke: every shipped module imports, or fails only for want of GTK.

``py-modules`` in pyproject.toml is what a wheel installs. A module that is
declared but cannot be imported (syntax error, bad top-level import, missing
sibling) would break installed builds, so each one is imported in a fresh
isolated interpreter. GTK-bound modules are allowed to fail on ``gi`` alone,
which keeps this runnable on headless CI without a display.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Regex, not tomllib: the project supports Python 3.10, which has no tomllib.
_BLOCK = re.search(r"^py-modules = \[(.*?)^\]", (ROOT / "pyproject.toml").read_text("utf-8"),
                   re.S | re.M)
MODULES = re.findall(r'"([A-Za-z0-9_]+)"', _BLOCK.group(1)) if _BLOCK else []
GTK_ROOTS = ("gi", "Gtk", "Gdk", "Adw", "GLib", "Gio", "GObject")


def _import(name: str) -> subprocess.CompletedProcess[str]:
    code = f"import sys; sys.path.insert(0, {str(SRC)!r}); import {name}"
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True,
                          text=True, timeout=60, cwd=ROOT)


def _missing_gtk(stderr: str) -> bool:
    return any(f"No module named '{root}" in stderr or f"cannot import name '_{root}'" in stderr
               or f"{root}.repository" in stderr for root in GTK_ROOTS) or "_gi" in stderr


def test_pyproject_module_list_was_parsed():
    assert len(MODULES) > 100


def test_declared_modules_exist_on_disk():
    missing = [m for m in MODULES if not (SRC / f"{m}.py").is_file()]
    assert not missing, f"declared in pyproject but absent from src/: {missing}"


def test_declared_modules_are_unique_and_sorted():
    assert len(set(MODULES)) == len(MODULES)
    assert MODULES == sorted(MODULES)


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_headlessly(name: str):
    result = _import(name)
    if result.returncode == 0:
        return
    if _missing_gtk(result.stderr):
        pytest.skip(f"{name} needs GTK, unavailable in this environment")
    pytest.fail(f"import {name} failed:\n{result.stderr[-800:]}")
