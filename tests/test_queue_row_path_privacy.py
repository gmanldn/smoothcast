"""GTK-free proof that a queue row never exposes its source path as a tooltip."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"


def method_in(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    matches = [item for cls in tree.body if isinstance(cls, ast.ClassDef)
               for item in cls.body if isinstance(item, ast.FunctionDef)
               and item.name == name]
    assert len(matches) == 1
    return matches[0]


def calls_to(method: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [item for item in ast.walk(method) if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute) and item.func.attr == name]


def private_path_reads(method: ast.FunctionDef) -> list[ast.Call]:
    return [item for item in ast.walk(method) if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name) and item.func.id == "getattr"
            and len(item.args) >= 2 and isinstance(item.args[1], ast.Constant)
            and item.args[1].value == "source_path"]


def test_tooltip_uses_display_title_never_absolute_source_path():
    row = method_in("queue_row_ui.py", "_queue_row")
    # The drag handle has its own static usage hint; inspect only the row title.
    tooltip = [call for call in calls_to(row, "set_tooltip_text")
               if isinstance(call.func.value, ast.Name) and call.func.value.id == "row"]
    assert len(tooltip) == 1
    assert isinstance(tooltip[0].args[0], ast.Name)
    assert tooltip[0].args[0].id == "display_title"
    stored = [item for item in ast.walk(row) if isinstance(item, ast.Assign)
              and any(isinstance(t, ast.Attribute) and t.attr == "source_path"
                      for t in item.targets)]
    assert len(stored) == 1
    assert isinstance(stored[0].value, ast.Name) and stored[0].value.id == "path"


def test_filtered_selection_activation_still_use_stable_private_file_identity():
    for module, name in (
        ("queue_row_ui.py", "_queue_row_matches"),
        ("cast_queue.py", "_on_queue_selected"),
        ("cast_queue.py", "_on_queue_activated"),
    ):
        method = method_in(module, name)
        assert private_path_reads(method), f"{name} must keep stable source identity"
        assert not calls_to(method, "get_tooltip_text"), (
            f"{name} must not recover an internal path from visible UI copy"
        )
        assert not calls_to(method, "get_index"), (
            f"{name} must not confuse filtered row index with source identity"
        )
