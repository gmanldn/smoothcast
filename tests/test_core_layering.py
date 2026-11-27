"""Layering contract (ARCH-02, #690): core modules depend only on other core modules.

The dependency direction is core <- platform <- services <- ui <- app. A core module
importing any other ``src`` module is an upward import. Today's violations are frozen in
``KNOWN`` and may only shrink; the report lists them so the next slice can fix each.
"""
from __future__ import annotations

from pathlib import Path

from test_core_purity import CORE, SRC, _imports

# module -> src modules it imports although they are not core (today's debt).
KNOWN: dict[str, set[str]] = {"hw_encoder_state": {"media_tools"}}


def violations() -> dict[str, set[str]]:
    src_modules = {p.stem for p in SRC.glob("*.py")}
    found = {}
    for name in CORE:
        bad = {m for m in _imports(SRC / f"{name}.py") if m in src_modules and m not in CORE and m != name}
        if bad:
            found[name] = bad
    return found


def test_core_imports_only_core():
    found = violations()
    worse = {n: sorted(b - KNOWN.get(n, set())) for n, b in found.items() if b - KNOWN.get(n, set())}
    assert not worse, f"core module imports a non-core module (upward import): {worse}"


def test_known_debt_only_shrinks():
    found = violations()
    fixed = {n: sorted(b - found.get(n, set())) for n, b in KNOWN.items() if b - found.get(n, set())}
    assert not fixed, f"remove from KNOWN, these are fixed: {fixed}"
