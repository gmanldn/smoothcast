"""Layering ratchet (ARCH-02, #690): no new module-level import cycles in src/.

Only imports executed at import time count (top level, including ``try`` and
``if`` bodies); imports inside functions are deliberate cycle breakers. The
allowlist holds today's cycles and may only shrink.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

# Each entry is a sorted tuple of the modules in one strongly connected component.
KNOWN_CYCLES: set[tuple[str, ...]] = {("cast_app_lifecycle", "cast_control")}


def _top_level_imports(tree: ast.Module, names: set[str]) -> set[str]:
    found: set[str] = set()

    def visit(body):
        for node in body:
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body)
                visit(getattr(node, "orelse", []))
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
    visit(tree.body)
    return found & names


def _graph() -> dict[str, set[str]]:
    names = {p.stem for p in SRC.glob("*.py")}
    graph = {}
    for path in SRC.glob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        graph[path.stem] = _top_level_imports(tree, names) - {path.stem}
    return graph


def _components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    """Tarjan's strongly connected components, iterative; only those with a cycle."""
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for root in graph:
        if root in index:
            continue
        work = [(root, iter(sorted(graph[root])))]
        index[root] = low[root] = counter[0]; counter[0] += 1
        stack.append(root); on.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter[0]; counter[0] += 1
                    stack.append(child); on.add(child)
                    work.append((child, iter(sorted(graph.get(child, ())))))
                    advanced = True
                    break
                if child in on:
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    member = stack.pop(); on.discard(member); comp.append(member)
                    if member == node:
                        break
                if len(comp) > 1:
                    out.append(tuple(sorted(comp)))
    return out


def test_no_new_import_cycles():
    found = set(_components(_graph()))
    assert found <= KNOWN_CYCLES, f"new import cycle(s): {sorted(found - KNOWN_CYCLES)}"


def test_known_cycles_are_still_real():
    stale = KNOWN_CYCLES - set(_components(_graph()))
    assert not stale, f"cycle(s) fixed; delete from KNOWN_CYCLES: {sorted(stale)}"
