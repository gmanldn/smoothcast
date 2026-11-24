"""Responsive geometry and breakpoint regression tests (GTK-free)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from responsive_layout import (
    HEADER_HEIGHT, PANEL_MAX, PANEL_MIN, STACK_BELOW, layout_for_size, window_size,
)


class ResponsiveLayoutTests(unittest.TestCase):
    def test_large_window_keeps_two_columns_and_full_controls(self):
        state = layout_for_size(1600, 950)
        self.assertFalse(state.stacked)
        self.assertFalse(state.transport_wrapped)
        self.assertFalse(state.actions_wrapped)
        self.assertFalse(state.compact)

    def test_standard_laptop_keeps_the_side_panel_beside_the_player(self):
        state = layout_for_size(1024, 700)
        self.assertFalse(state.stacked)
        self.assertTrue(state.compact)
        self.assertFalse(state.transport_wrapped)
        self.assertEqual(state.margin, 8)
        self.assertEqual(state.panel_width, PANEL_MIN)

    def test_below_the_breakpoint_the_panel_stacks_under_the_player(self):
        self.assertFalse(layout_for_size(STACK_BELOW, 800).stacked)
        stacked = layout_for_size(STACK_BELOW - 1, 800)
        self.assertTrue(stacked.stacked)
        self.assertEqual(stacked.panel_width, 0)

    def test_narrow_window_wraps_transport_and_actions(self):
        state = layout_for_size(360, 800)
        self.assertTrue(state.stacked)
        self.assertTrue(state.transport_wrapped)
        self.assertTrue(state.actions_wrapped)
        self.assertEqual(state.action_columns, 2)
        self.assertTrue(state.tabs_icon_only)
        self.assertEqual(state.preview_height, 180)

    def test_panel_width_is_bounded_and_grows_with_the_window(self):
        widths = [layout_for_size(w, 900).panel_width for w in (960, 1280, 1600, 3000)]
        self.assertEqual(widths, sorted(widths))
        self.assertTrue(all(PANEL_MIN <= w <= PANEL_MAX for w in widths))

    def test_measured_transport_width_decides_when_to_wrap(self):
        # A big font makes the one-row controls wider: the card must wrap
        # earlier, or the wide layout's minimum width would trap the window.
        normal = layout_for_size(1100, 900, transport_min=548)
        large = layout_for_size(1100, 900, transport_min=900)
        self.assertFalse(normal.transport_wrapped)
        self.assertTrue(large.transport_wrapped)

    def test_preview_shrinks_so_the_whole_player_fits_the_window(self):
        roomy = layout_for_size(1280, 800)
        tight = layout_for_size(1280, 800, player_fixed=560)
        self.assertLess(tight.preview_height, roomy.preview_height)
        player = tight.preview_height + 560 + HEADER_HEIGHT + 2 * tight.margin
        self.assertLessEqual(player, 800)
        # Stacked pages scroll anyway, so the measurement is ignored there.
        self.assertEqual(layout_for_size(700, 800, player_fixed=560),
                         layout_for_size(700, 800))

    def test_resizing_back_restores_desktop_layout(self):
        original = layout_for_size(1420, 900)
        narrow = layout_for_size(580, 680)
        again = layout_for_size(1420, 900)
        self.assertNotEqual(original, narrow)
        self.assertEqual(original, again)

    def test_screen_size_limits_saved_giant_window(self):
        self.assertEqual(window_size(1600, 1000, 1366, 768), (1161, 652))
        self.assertEqual(window_size(2500, 1800, 1920, 1080), (1632, 918))

    def test_bad_saved_geometry_uses_safe_defaults(self):
        self.assertEqual(window_size("NaN", None), (1180, 760))
        self.assertEqual(window_size(-5, "inf"), (1180, 760))
        self.assertEqual(window_size(0, 0, 600, 500), (510, 404))


if __name__ == "__main__":
    unittest.main()
