"""GTK4 responsive UI wiring checks that run without PyGObject or a display."""
from pathlib import Path
import ast
import unittest

GUI = Path(__file__).resolve().parents[1] / "src" / "cast_control.py"


class ResponsiveGtkWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GUI.read_text(encoding="utf-8")

    def test_main_module_parses(self):
        ast.parse(self.source, filename=str(GUI))

    def test_ui_uses_single_scrollable_page_not_fixed_paned(self):
        self.assertIn("self.page_scroller.set_child(self.page)", self.source)
        self.assertIn("self.page.append(self.left_column)", self.source)
        self.assertIn("self.page.append(self.right_column)", self.source)
        self.assertNotIn("Gtk.Paned(", self.source)
        self.assertNotIn("self.set_size_request(1400, 900)", self.source)
        self.assertIn("self.set_size_request(360, 320)", self.source)

    def test_layout_reads_actual_window_allocation(self):
        self.assertIn("width = self.get_width() or self._startup_width", self.source)
        self.assertIn("height = self.get_height() or self._startup_height", self.source)
        self.assertIn("responsive_layout.layout_for_size(width, height)", self.source)
        self.assertIn("GLib.timeout_add(200, self._refresh_responsive_layout)", self.source)

    def test_transport_and_actions_reflow_in_grids(self):
        self.assertIn("Gtk.Grid(column_spacing=8, row_spacing=8)", self.source)
        self.assertIn("if state.transport_wrapped:", self.source)
        self.assertIn("if state.actions_wrapped else (n, 0)", self.source)
        self.assertIn("self.transport_grid.attach(button, column, row, 1, 1)", self.source)
        self.assertIn("self.action_grid.attach(child, col, row, 1, 1)", self.source)

    def test_long_text_wraps_instead_of_forcing_width(self):
        self.assertIn("Pango.WrapMode.WORD_CHAR", self.source)
        self.assertIn("value_label.set_max_width_chars(36)", self.source)
        self.assertIn("cr.show_text(clipped_text(title))", self.source)

    def test_no_gtk3_window_positioning(self):
        self.assertNotIn("self.move(", self.source)
        self.assertNotIn("self.get_position()", self.source)


if __name__ == "__main__":
    unittest.main()
