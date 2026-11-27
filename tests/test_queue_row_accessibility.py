"""Static queue-row accessibility contracts, without importing GTK (#449)."""
from __future__ import annotations

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src" / "queue_row_ui.py"


def test_queue_rows_announce_title_ordinal_and_state_without_private_path():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "QueueRowMixin")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_queue_row")
    calls = [node for node in ast.walk(method)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "update_property"
             and isinstance(node.func.value, ast.Name) and node.func.value.id == "row"]
    assert len(calls) == 1, "ListBoxRow must have exactly one explicit accessible label"
    source = ast.unparse(calls[0])
    assert "AccessibleProperty.LABEL" in source
    assert "display_title" in source
    assert "index + 1" in source
    assert "len(self.queue)" in source
    assert "playback_state" in source
    assert "path" not in source, "An accessible label must not announce private media paths"


def test_queue_row_label_stays_in_step_with_rebuilt_position_and_playback():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "QueueRowMixin")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_queue_row")
    source = ast.unparse(method)
    assert 'path == self.now_playing' in source
    literals = {node.value for node in ast.walk(method)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert "Now playing" in literals
    assert "Queued" in literals
    assert "queue_metadata.display_title(path, self._media_cache, display_name)" in source
    assert "row.display_title = display_title" in source
