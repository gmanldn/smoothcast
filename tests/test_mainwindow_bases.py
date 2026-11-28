"""Ratchet (ARCH-03, #691): ``MainWindow`` must not gain base classes.

It inherits 17 bases today (16 mixins plus the GTK window). Each extraction
lowers MAX_BASES; the target is 3. Parsed from source, no GTK import.
"""
from __future__ import annotations

import ast
from pathlib import Path

MAX_BASES = 8
SRC = Path(__file__).resolve().parents[1] / "src" / "cast_control.py"


def test_mainwindow_does_not_gain_bases():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    assert len(cls.bases) <= MAX_BASES, (
        f"MainWindow has {len(cls.bases)} bases (max {MAX_BASES}): add a component with an "
        "injected port instead of another mixin (#691)")
