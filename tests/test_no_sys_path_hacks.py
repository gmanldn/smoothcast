"""Ratchet (ARCH-02, #690): no new ``sys.path`` mutation in src/ or setup/.

Each hack hides a layering violation. The allowlist holds today's three and may only shrink.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "setup/fresh_start.py": 1,
    "setup/launch.py": 1,
}
_MUTATION = re.compile(r"sys\.path\s*(?:\.\s*(?:insert|append|extend)\s*\(|\+=|\[\s*:\s*\]\s*=)")


def test_sys_path_mutation_never_grows():
    found = {}
    for folder in ("src", "setup"):
        for path in (ROOT / folder).rglob("*.py"):
            count = len(_MUTATION.findall(path.read_text(encoding="utf-8", errors="replace")))
            if count:
                found[str(path.relative_to(ROOT))] = count
    worse = {n: (c, ALLOWED.get(n, 0)) for n, c in found.items() if c > ALLOWED.get(n, 0)}
    assert not worse, f"new sys.path mutation (found, allowed): {worse}; fix the layering instead"
    stale = {n for n in ALLOWED if found.get(n, 0) < ALLOWED[n]}
    assert not stale, f"shrink ALLOWED, these are fixed: {sorted(stale)}"
