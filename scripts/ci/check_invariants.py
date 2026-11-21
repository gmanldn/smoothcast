#!/usr/bin/env python3
"""Fail CI when architecture safety invariants lose executable regression guards.

Pure standard library: no imports from production code, GTK or network I/O.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"INV-\d{3}\Z")
REFERENCES = re.compile(r"INV-\d{3}")
MARKER = re.compile(r"<!--\s*invariant:\s*([^>]+)\s*-->")
ROW = re.compile(r"^\|\s*(INV-\d{3})\s*\|")


def _test_node(tree: ast.Module, node_id: str):
    parts = node_id.split("::")
    scope: list[ast.stmt] = tree.body
    selected = None
    for part in parts:
        selected = next((node for node in scope
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                              ast.ClassDef)) and node.name == part), None)
        if selected is None:
            return None
        scope = getattr(selected, "body", [])
    return selected if isinstance(selected, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    matrix_path = root / "docs" / "INVARIANTS.md"
    architecture_path = root / "docs" / "agents" / "architecture.md"
    try:
        lines = matrix_path.read_text(encoding="utf-8").splitlines()
        architecture = architecture_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"Invariant evidence document missing: {exc}"]

    markers = []
    for raw in MARKER.findall(architecture):
        markers.extend(REFERENCES.findall(raw))
    if len(markers) != len(set(markers)):
        errors.append("Architecture repeats an invariant marker")
    rows: dict[str, tuple[str, str]] = {}
    for line in lines:
        if not ROW.match(line):
            continue
        fields = [value.strip() for value in line.strip().strip("|").split("|")]
        if len(fields) != 4:
            errors.append(f"Malformed invariant matrix row: {line[:100]}")
            continue
        identifier, description, owner, node_id = fields
        if identifier in rows:
            errors.append(f"Duplicate matrix invariant: {identifier}")
            continue
        if not IDENTIFIER.fullmatch(identifier) or not description or not owner or not node_id:
            errors.append(f"Incomplete invariant row: {identifier}")
            continue
        rows[identifier] = (owner, node_id)
        if not owner.startswith("src/") or not owner.endswith(".py") or not (root / owner).is_file():
            errors.append(f"{identifier}: missing or invalid owner {owner}")
        test_path, *node_parts = node_id.split("::")
        if (not test_path.startswith("tests/") or not test_path.endswith(".py")
                or not node_parts):
            errors.append(f"{identifier}: invalid pytest node ID {node_id}")
            continue
        target = root / test_path
        try:
            tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        except (OSError, SyntaxError) as exc:
            errors.append(f"{identifier}: guard test unavailable: {exc}")
            continue
        node = _test_node(tree, "::".join(node_parts))
        if node is None or not node.name.startswith("test_"):
            errors.append(f"{identifier}: named pytest guard does not exist: {node_id}")
            continue
        docstring = ast.get_docstring(node) or ""
        if identifier not in docstring:
            errors.append(f"{identifier}: guarding test docstring lacks bidirectional reference: {node_id}")
        has_assert = any(
            isinstance(child, ast.Assert)
            or (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr.startswith("assert"))
            for child in ast.walk(node)
        )
        if not has_assert:
            errors.append(f"{identifier}: guard has no direct assertion: {node_id}")

    for identifier in sorted(set(markers) - set(rows)):
        errors.append(f"{identifier}: architecture marker has no matrix row")
    for identifier in sorted(set(rows) - set(markers)):
        errors.append(f"{identifier}: matrix row has no architecture marker")
    if not rows:
        errors.append("The invariant matrix contains no guard rows")
    return errors


def main() -> int:
    errors = validate(ROOT)
    if errors:
        for error in errors:
            print("INVARIANT FAIL:", error)
        return 1
    print("INVARIANTS OK: safety markers, owner modules and pytest nodes are linked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
