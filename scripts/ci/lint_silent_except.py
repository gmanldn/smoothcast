#!/usr/bin/env python3
"""Ratcheted AST check: new broad silent playback exception handlers are forbidden.

The baseline is an explicit, reviewed exception list. Findings use their
enclosing function and first guarded statement, not source line numbers.
    python scripts/ci/lint_silent_except.py
    python scripts/ci/lint_silent_except.py --report
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "silent-except-baseline.json"
PLAYBACK_FILES = (
    "src/cast_session.py",
    "src/streamer.py",
    "src/dlna.py",
    "src/castctl.py",
    "src/direct_probe.py",
    "src/stream_watchdog.py",
    "src/cast_queue.py",
)
BROAD = frozenset({"Exception", "BaseException"})


def _broad(handler: ast.ExceptHandler) -> str | None:
    if handler.type is None:
        return "bare"
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    names = [item.id for item in nodes if isinstance(item, ast.Name)]
    return "+".join(sorted(BROAD.intersection(names))) or None


def _silent(handler: ast.ExceptHandler) -> bool:
    if len(handler.body) != 1:
        return False
    stmt = handler.body[0]
    return (isinstance(stmt, (ast.Pass, ast.Continue)) or
            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis)


def scan_source(source: str, filename: str) -> list[dict[str, str]]:
    """Detect only broad exception swallowing; retain no private source contents."""
    tree = ast.parse(source, filename=filename)
    found: list[dict[str, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        def visit_Try(self, node: ast.Try) -> None:
            guarded = ast.get_source_segment(source, node.body[0]) if node.body else ""
            first_line = (guarded or "").splitlines()[0].strip() if guarded else "<empty>"
            for handler in node.handlers:
                kind = _broad(handler)
                if kind and _silent(handler):
                    key = "|".join((filename, ".".join(self.scope) or "<module>",
                                    kind, first_line))
                    found.append({"key": key, "line": str(handler.lineno)})
            self.generic_visit(node)

        if hasattr(ast, "TryStar"):
            visit_TryStar = visit_Try

    Visitor().visit(tree)
    keys = [item["key"] for item in found]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{filename}: duplicate silent handler fingerprints; "
                         "refine the key before accepting a baseline")
    return found


def audit(root: Path, baseline: Path) -> tuple[list[dict[str, str]], list[str]]:
    all_found: list[dict[str, str]] = []
    for relative in PLAYBACK_FILES:
        all_found.extend(scan_source((root / relative).read_text(encoding="utf-8"), relative))
    try:
        entries: Any = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return all_found, [f"Cannot read exception baseline: {exc}"]
    if (not isinstance(entries, list) or any(
            not isinstance(entry, dict) or
            not isinstance(entry.get("key"), str) or
            not isinstance(entry.get("reason"), str) or not entry["reason"].strip()
            for entry in entries)):
        return all_found, ["Exception baseline requires key/reason pairs"]
    allowed = {entry["key"] for entry in entries}
    if len(allowed) != len(entries):
        return all_found, ["Exception baseline contains duplicate keys"]
    actual = {item["key"] for item in all_found}
    errors = [f"NEW silent broad exception: {key}" for key in sorted(actual - allowed)]
    errors += [f"STALE baseline entry, remove it: {key}" for key in sorted(allowed - actual)]
    return all_found, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--report", action="store_true", help="print current findings as JSON")
    args = parser.parse_args(argv)
    try:
        found, problems = audit(args.root, args.baseline)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"silent-except audit failed: {exc}")
        return 2
    if args.report:
        print(json.dumps(found, indent=2, ensure_ascii=True))
        return 0
    for problem in problems:
        print(problem)
    if problems:
        print("Review and remove existing findings or add justified, narrow baseline exceptions.")
        return 1
    print(f"Silent-exception ratchet clean ({len(found)} grandfathered cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
