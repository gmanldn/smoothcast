"""Static guard: every ``from <src module> import name`` must resolve.

Pytest is headless and never imports the GTK modules, so a bad import in
``cast_control`` (e.g. a mixin moved to another module) once shipped to
``develop`` and crashed the app at startup. This AST check needs no GTK.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _top_level_names(tree: ast.Module) -> set[str] | None:
    """Names a module defines at top level; None if it uses ``import *``/``__getattr__``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == "__getattr__":
                return None
    for node in tree.body:
        stack = [node]
        while stack:
            item = stack.pop()
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(item.name)
            elif isinstance(item, (ast.Import, ast.ImportFrom)):
                for alias in item.names:
                    if alias.name == "*":
                        return None
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            names.add(sub.id)
            elif isinstance(item, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for field in ("body", "orelse", "finalbody", "handlers"):
                    for child in getattr(item, field, []) or []:
                        stack.extend(child.body if isinstance(child, ast.ExceptHandler)
                                     else [child])
    return names


def test_local_from_imports_resolve() -> None:
    modules = {path.stem: path for path in SRC.glob("*.py")}
    defined = {stem: _top_level_names(ast.parse(path.read_text(encoding="utf-8")))
               for stem, path in modules.items()}
    problems = []
    for stem, path in sorted(modules.items()):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.level == 0
                    and node.module in modules):
                continue
            known = defined[node.module]
            if known is None:
                continue
            for alias in node.names:
                if alias.name != "*" and alias.name not in known:
                    # A submodule-style import of a sibling file is also fine.
                    problems.append(f"{stem}.py:{node.lineno} imports "
                                    f"{alias.name!r} from {node.module}, which lacks it")
    assert not problems, "\n".join(problems)


def test_guard_detects_missing_name() -> None:
    tree = ast.parse("class A: pass\nB = 1\nfrom x import C\n")
    assert _top_level_names(tree) == {"A", "B", "C"}
