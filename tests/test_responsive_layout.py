"""Responsive geometry and breakpoint regression tests (GTK-free)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from responsive_layout import layout_for_size, window_size


class ResponsiveLayoutTests(unittest.TestCase):
    def test_large_window_keeps_two_columns_and_full_controls(self):
        state = layout_for_size(1600, 950)
        self.assertFalse(state.stacked)
        self.assertFalse(state.transport_wrapped)
        self.assertFalse(state.actions_wrapped)
        self.assertFalse(state.compact)

    def test_standard_laptop_reflows_to_single_column(self):
        state = layout_for_size(1024, 700)
        self.assertTrue(state.stacked)
        self.assertTrue(state.compact)
        self.assertFalse(state.transport_wrapped)
        self.assertEqual(state.margin, 8)

    def test_narrow_window_wraps_transport_and_actions(self):
        state = layout_for_size(480, 650)
        self.assertTrue(state.stacked)
        self.assertTrue(state.transport_wrapped)
        self.assertTrue(state.actions_wrapped)
        self.assertEqual(state.preview_height, 110)

    def test_resizing_back_restores_desktop_layout(self):
        original = layout_for_size(1420, 900)
        narrow = layout_for_size(580, 680)
        again = layout_for_size(1420, 900)
        self.assertNotEqual(original, narrow)
        self.assertEqual(original, again)

    def test_screen_size_limits_saved_giant_window(self):
        self.assertEqual(window_size(1600, 1000, 1366, 768), (1294, 672))
        self.assertEqual(window_size(2500, 1800, 1920, 1080), (1848, 984))

    def test_bad_saved_geometry_uses_safe_defaults(self):
        self.assertEqual(window_size("NaN", None), (1180, 760))
        self.assertEqual(window_size(-5, "inf"), (1180, 760))
        self.assertEqual(window_size(0, 0, 600, 500), (528, 404))


if __name__ == "__main__":
    unittest.main()
