"""Ratchet (#699): tests must not assert behaviour by reading production source text.

Such tests break on harmless refactors and prove nothing about behaviour. Files that
already do it are frozen in ``source_text_baseline.json``; the list may only shrink.
Heuristic: ``inspect.getsource``, ``main_window_methods`` or ``read_text`` of a ``src`` file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BASELINE = TESTS / "source_text_baseline.json"
_READS_SOURCE = re.compile(
    r"inspect\.getsource|main_window_methods"
    r"|(?:SRC|ROOT|src)[^\n]{0,40}/\s*\"[a-z_0-9]+\.py\"\)\.read_text"
    r"|\(SRC\s*/\s*\"[a-z_0-9]+\.py\"\)\.read_text")


def current() -> set[str]:
    me = Path(__file__).name
    return {p.name for p in TESTS.glob("test_*.py")
            if p.name != me and _READS_SOURCE.search(p.read_text(encoding="utf-8", errors="replace"))}


def test_no_new_source_text_tests():
    allowed = set(json.loads(BASELINE.read_text())["files"])
    new = current() - allowed
    assert not new, f"write behavioural tests instead of reading source text: {sorted(new)}"


def test_baseline_only_shrinks():
    allowed = set(json.loads(BASELINE.read_text())["files"])
    fixed = allowed - current()
    assert not fixed, f"remove from source_text_baseline.json (converted): {sorted(fixed)}"
