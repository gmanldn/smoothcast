"""Queue accessibility handoff tests without GTK or real media files (#449)."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import queue_accessibility


class _Row:
    def __init__(self):
        self.classes = set()
        self.labels = []

    def add_css_class(self, value):
        self.classes.add(value)

    def remove_css_class(self, value):
        self.classes.discard(value)

    def update_property(self, property_names, values):
        assert len(property_names) == 1
        self.labels.append(values[0])


class _Rows:
    def __init__(self, count):
        self.rows = [_Row() for _ in range(count)]
        self.lookups = 0

    def get_row_at_index(self, index):
        self.lookups += 1
        return self.rows[index] if index < len(self.rows) else None


class _Gtk:
    class AccessibleProperty:
        LABEL = "label"


def _window():
    queue = ["/private/videos/first.mp4", "/secret/second.mp4"]
    rows = _Rows(len(queue))
    return SimpleNamespace(queue=queue, queue_list=rows, _media_cache={},
                           now_playing=None), rows


def test_handoff_updates_previous_and_current_spoken_rows():
    window, rows = _window()
    window.now_playing = window.queue[0]
    queue_accessibility.sync_rows(window, _Gtk)
    assert rows.rows[0].labels[-1] == "first.mp4, 1 of 2, Now playing"
    assert rows.rows[0].classes == {"current"}
    assert rows.rows[1].labels == []

    window.now_playing = window.queue[1]
    queue_accessibility.sync_rows(window, _Gtk)
    assert rows.rows[0].labels[-1] == "first.mp4, 1 of 2, Queued"
    assert rows.rows[1].labels[-1] == "second.mp4, 2 of 2, Now playing"
    assert rows.rows[0].classes == set()
    assert rows.rows[1].classes == {"current"}
    assert all("/private/" not in s and "/secret/" not in s
               for row in rows.rows for s in row.labels)


def test_unchanged_playback_has_constant_time_no_row_lookup():
    window, rows = _window()
    window.now_playing = window.queue[1]
    queue_accessibility.sync_rows(window, _Gtk)
    looked_up = rows.lookups
    queue_accessibility.sync_rows(window, _Gtk)
    assert rows.lookups == looked_up
    window.now_playing = None
    queue_accessibility.sync_rows(window, _Gtk)
    assert rows.rows[1].labels[-1].endswith("Queued")
    assert "current" not in rows.rows[1].classes
    looked_up = rows.lookups
    queue_accessibility.sync_rows(window, _Gtk)
    assert rows.lookups == looked_up


def test_refresh_controls_wires_accessibility_without_gtk_import_in_helper():
    src = Path(__file__).resolve().parents[1] / "src"
    tree = ast.parse((src / "cast_ui.py").read_text(encoding="utf-8"))
    method = next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                  for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_refresh_controls")
    text = ast.unparse(method)
    assert 'hasattr(self, "queue_list")' in text
    assert "queue_accessibility.sync_rows(self, Gtk)" in text
    helper = ast.parse((src / "queue_accessibility.py").read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(helper)
               if isinstance(node, ast.ImportFrom)}
    assert imports == {"__future__"}
    assert all(node.names[0].name != "gi" for node in ast.walk(helper)
               if isinstance(node, ast.Import))
