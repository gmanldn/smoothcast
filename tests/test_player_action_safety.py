"""Regression checks for GUI actions that must not clobber active TV state.

No GTK display is needed: inspect the exact MainWindow methods for unsafe
side effects that have previously broken queue navigation and autoplay.
"""
from pathlib import Path
import ast
import unittest

SOURCE_FILE = Path(__file__).resolve().parents[1] / "src" / "cast_control.py"


class PlayerActionSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SOURCE_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SOURCE_FILE))
        window = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        cls.methods = {
            node.name: ast.get_source_segment(source, node)
            for node in window.body if isinstance(node, ast.FunctionDef)
        }

    def test_busy_queue_next_does_not_preassign_current_media(self):
        for method in ("on_next", "on_prev", "_on_queue_activated"):
            with self.subTest(method=method):
                body = self.methods[method]
                self.assertNotIn("self.now_playing =", body)
                self.assertIn("self._cast_path(", body)

    def test_play_without_owned_session_starts_selected_media(self):
        code = self.methods["toggle_play"]
        self.assertIn("if self.session is None and not self.external:", code)
        self.assertIn("self.cast_selected()", code)
        self.assertIn("castctl.play(device)", code)  # only in the real session branch

    def test_completion_cleanup_does_not_stop_new_tv_content(self):
        code = self.methods["_on_finished"]
        self.assertIn("session.stop(device, send_stop=False)", code)
        self.assertNotIn("lambda: session.stop(device),", code)

    def test_explicit_start_and_resume_are_distinct(self):
        gui = self.methods["_cast_path"]
        self.assertIn("offset: float | None = None", gui)
        self.assertIn("playback_state.start_offset(", gui)
        self.assertIn("self._cast_path(next_path, 0.0)", self.methods["_on_finished"])
        self.assertIn("self._cast_path(path, None)", self.methods["open_recent"])


if __name__ == "__main__":
    unittest.main()
