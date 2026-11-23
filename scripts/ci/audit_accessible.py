#!/usr/bin/env python3
"""Static inventory of GTK interactive widgets and whether each has an accessible name (#449).

GTK4 has no public getter for a widget's computed accessible name, so this reads
the source instead (stdlib ``ast``; never imports GTK). A widget counts as
*labelled* when its constructor passes ``label=``/``tooltip_text=`` (or uses
``new_with_label``), or the same function later calls ``set_label``,
``set_tooltip_text``, ``update_property`` or ``update_relation`` on it.
``--write-baseline`` records today's unlabelled widgets; the test is a ratchet.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "a11y-baseline.json"
INTERACTIVE = {
    "Gtk.Button", "Gtk.ToggleButton", "Gtk.MenuButton", "Gtk.Scale", "Gtk.Switch",
    "Gtk.Entry", "Gtk.SearchEntry", "Gtk.SpinButton", "Gtk.DropDown", "Gtk.CheckButton",
    "Gtk.LinkButton",
}
LABEL_CALLS = {"set_label", "set_tooltip_text", "update_property", "update_relation"}
LABEL_KWARGS = {"label", "tooltip_text", "title"}


def _kind(call: ast.Call) -> tuple[str, bool] | None:
    name = ast.unparse(call.func)
    base, _, ctor = name.rpartition(".")
    if name in INTERACTIVE:
        return name, any(k.arg in LABEL_KWARGS for k in call.keywords)
    if base in INTERACTIVE and ctor.startswith("new"):
        return base, ctor == "new_with_label" or ctor == "new_with_mnemonic"
    return None


def _scan_function(path: Path, func: ast.AST, qual: str) -> list[dict]:
    created: list[dict] = []
    labelled: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            made = _kind(node.value)
            if made and len(node.targets) == 1:
                created.append({"target": ast.unparse(node.targets[0]), "kind": made[0],
                                "inline": made[1], "line": node.lineno})
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in LABEL_CALLS:
                labelled.add(ast.unparse(node.func.value))
            elif made := _kind(node):
                # An unassigned constructor: still counted, keyed by line.
                if not any(item["line"] == node.lineno for item in created):
                    created.append({"target": f"<anonymous@{node.lineno}>", "kind": made[0],
                                    "inline": made[1], "line": node.lineno})
    return [{"file": path.name, "function": qual, "target": c["target"], "kind": c["kind"],
             "line": c["line"], "labelled": c["inline"] or c["target"] in labelled}
            for c in created]


def audit(src: Path = ROOT / "src") -> list[dict]:
    found: list[dict] = []
    for path in sorted(src.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "from gi.repository" not in text or "Gtk" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.extend(_scan_function(path, node, node.name))
    # Nested functions are walked twice; keep one record per site.
    unique = {(r["file"], r["line"], r["target"]): r for r in found}
    return sorted(unique.values(), key=lambda r: (r["file"], r["line"]))


def key(record: dict) -> str:
    """Line-independent identity so edits elsewhere do not churn the baseline."""
    return f"{record['file']}::{record['function']}::{record['target']}::{record['kind']}"


def unlabelled(records: list[dict]) -> list[str]:
    return sorted({key(r) for r in records if not r["labelled"]})


def main(argv: list[str]) -> int:
    records = audit()
    todo = unlabelled(records)
    print(f"{len(records)} interactive widgets, {len(todo)} without an accessible name")
    if "--write-baseline" in argv:
        BASELINE.write_text(json.dumps({"unlabelled": todo}, indent=1) + "\n", encoding="utf-8")
        print(f"baseline written: {len(todo)} entries")
    elif "--list" in argv:
        print("\n".join(todo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
