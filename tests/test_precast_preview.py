"""Source-level guards for local pre-cast film inspection (GTK-free)."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/cast_control.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
              and node.name == "MainWindow")
METHODS = {
    node.name: ast.get_source_segment(SOURCE, node)
    for node in WINDOW.body if isinstance(node, ast.FunctionDef)
}


class PreCastPreviewTests(unittest.TestCase):
    def test_file_selection_does_not_immediately_cast(self):
        self.assertIn("self.set_selection(path)", METHODS["_file_chosen"])
        self.assertNotIn("self._cast_path(", METHODS["_file_chosen"])

    def test_scrub_without_session_stays_local(self):
        seek = METHODS["seek_to"]
        self.assertIn("if session is None and self._preview_path is not None:", seek)
        local_branch = seek.split("if session is None and self._preview_path is not None:", 1)[1]
        self.assertLess(local_branch.index("self._queue_preview(target)"),
                        local_branch.index("return"))
        self.assertLess(local_branch.index("return"), local_branch.index("self._cast_path("))

    def test_cast_uses_explicit_preview_start_offset(self):
        cast = METHODS["cast_selected"]
        self.assertIn("self._preview_position", cast)
        self.assertIn("self._cast_path(pathlib.Path(path), start_at)", cast)

    def test_duration_and_frame_are_loaded_asynchronously(self):
        selection = METHODS["set_selection"]
        self.assertIn("streamer.ffprobe(", selection)
        self.assertIn("self.seekbar.set_state(self._preview_position, duration", selection)
        self.assertIn("self._queue_preview(self._preview_position)", selection)
        self.assertIn("Async.run(work, done=done)", selection)

    def test_scrub_thumbnails_are_throttled_and_do_not_run_on_gtk_thread(self):
        self.assertIn("self._preview_busy", METHODS["_start_preview"])
        self.assertIn("Async.run(", METHODS["_start_preview"])
        self.assertIn("screenshot.preview_frame(", METHODS["_start_preview"])
        self.assertIn("GLib.timeout_add(180, self._start_preview)", METHODS["_queue_preview"])
        self.assertIn("Gdk.Texture.new_from_bytes(", METHODS["_start_preview"])


if __name__ == "__main__":
    unittest.main()
