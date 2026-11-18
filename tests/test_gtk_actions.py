"""Guard against GTK3-only window APIs and unregistered menu actions.

Source-level tests intentionally run without a display, GTK or PyGObject.
"""
from pathlib import Path
import unittest

GUI = Path(__file__).resolve().parents[1] / "src" / "cast_control.py"


class Gtk4ActionTests(unittest.TestCase):
    def test_fullscreen_uses_gtk4_methods(self):
        source = GUI.read_text()
        self.assertIn("self.is_fullscreen()", source)
        self.assertIn("self.fullscreen()", source)
        self.assertIn("self.unfullscreen()", source)
        self.assertNotIn("self.set_fullscreen(", source)

    def test_gtk3_only_keep_above_not_advertised(self):
        source = GUI.read_text()
        self.assertNotIn("set_keep_above(", source)
        self.assertNotIn("get_keep_above(", source)
        self.assertNotIn('app.always-on-top', source)

    def test_clear_recents_menu_action_registered(self):
        source = GUI.read_text()
        self.assertIn('recents.append("Clear recent files", "app.clear-recents")', source)
        self.assertIn('simple("clear-recents", lambda *a: self._window()._clear_recents())', source)


if __name__ == "__main__":
    unittest.main()
