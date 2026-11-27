"""Broad-except ratchet (ARCH-06, #694): untagged ``except Exception`` only shrinks.

A broad catch is allowed with a justification tag (``# noqa: BLE001 - reason``) on its line.
Untagged ones are frozen per file in ``broad_except_baseline.json``; the baseline may only
go down. Fix a handler (catch the typed error, or tag it) and lower the number.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((Path(__file__).with_name("broad_except_baseline.json")).read_text())["files"]
BROAD = {"Exception", "BaseException"}


def _is_broad(node: ast.ExceptHandler) -> bool:
    t = node.type
    if t is None:
        return True
    names = t.elts if isinstance(t, ast.Tuple) else [t]
    return any(isinstance(n, ast.Name) and n.id in BROAD for n in names)


def counts() -> dict[str, int]:
    found = {}
    for path in sorted((ROOT / "src").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        n = sum(1 for node in ast.walk(tree)
                if isinstance(node, ast.ExceptHandler) and _is_broad(node)
                and "BLE001" not in lines[node.lineno - 1])
        if n:
            found[path.name] = n
    return found


def test_no_new_untagged_broad_except():
    worse = {n: (c, BASELINE.get(n, 0)) for n, c in counts().items() if c > BASELINE.get(n, 0)}
    assert not worse, f"untagged broad except (found, allowed); catch a typed error or tag it: {worse}"


def test_baseline_only_shrinks():
    found = counts()
    stale = {n: (b, found.get(n, 0)) for n, b in BASELINE.items() if found.get(n, 0) < b}
    assert not stale, f"lower broad_except_baseline.json (allowed, found): {stale}"
