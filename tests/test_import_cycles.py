"""Cycle ratchet (ARCH-02, #690): no new two-way top-level import between src modules.

Lazy (in-function) imports are the sanctioned way to break a cycle and are not counted.
Cycles that exist today are frozen in ``KNOWN`` and may only shrink.
"""
from __future__ import annotations

from test_core_purity import SRC, _imports

KNOWN: set[frozenset[str]] = {frozenset({"cast_app_lifecycle", "cast_control"})}


def cycles() -> set[frozenset[str]]:
    mods = {p.stem for p in SRC.glob("*.py")}
    graph = {m: {i for i in _imports(SRC / f"{m}.py") if i in mods and i != m} for m in mods}
    return {frozenset((a, b)) for a, deps in graph.items() for b in deps if a in graph[b]}


def test_no_new_two_way_imports():
    new = cycles() - KNOWN
    assert not new, f"new import cycles (import lazily or extract the shared part): {sorted(map(sorted, new))}"


def test_known_cycles_only_shrink():
    fixed = KNOWN - cycles()
    assert not fixed, f"remove from KNOWN, fixed: {sorted(map(sorted, fixed))}"
