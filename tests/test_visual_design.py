"""GTK-independent checks for SmoothCast's visual system and live UI wiring.

These exercise structural and contrast invariants in CI without requiring a
Chromecast, X11/Wayland display or a PyGObject installation.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gui_source import GUI_MODULES, combined_source

import ui_theme


class VisualDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = combined_source()
        cls.theme = ui_theme.CSS.decode("utf-8")

    def test_gtk_code_and_theme_are_valid_python(self):
        for name in (*GUI_MODULES, "ui_theme.py"):
            path = ROOT / "src" / name
            ast.parse(path.read_text("utf-8"), filename=str(path))

    def test_surfaces_and_primary_actions_use_native_colour_pairs(self):
        for role in ("card", "accent"):
            for channel in ("fg", "bg"):
                self.assertIn(f"@{role}_{channel}_color", self.theme)
        self.assertNotRegex(self.theme, r"#[0-9a-fA-F]{6}")

    def test_theme_keeps_semantic_control_hierarchy(self):
        for selector in (".hero-card", ".hero-title", ".big-play", ".primary-action",
                         ".setting-group", ".device-badge",
                         ".empty-state", ".detail-section", ".console-idle"):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.theme)

    def test_not_a_gtk_theme_only_mock(self):
        for snippet in (
            'CSS = ui_theme.CSS',
            'card.add_css_class("hero-card")',
            'card.add_css_class("settings-card")',
            'card.add_css_class("device-card")',
            'card.add_css_class("diagnostics-card")',
            'self._set_device_badge("STREAMING", "online")',
            'self.queue_scroller.set_visible(bool(visible))',
            'self.console_empty.set_visible(not has_activity)',
            'self.preview = PreviewScreen()',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, self.source)

    def test_original_playback_actions_remain_wired(self):
        for snippet in (
            'self.play_button.connect("clicked", lambda _b: self.toggle_play())',
            'self.cast_button.connect("clicked", lambda _b: self.cast_selected())',
            'self.stop_tv_button.connect("clicked", lambda _b: self.stop_stream())',
            'self.volume_scale.connect("value-changed", self._on_volume_changed)',
            'self.device_dropdown.connect("notify::selected", self._on_device_selected)',
            'self.seekbar = SeekBar(self.seek_to, self._on_hover)',
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, self.source)

    def test_primary_action_changes_with_selection(self):
        self.assertIn("self.open_button = open_button", self.source)
        self.assertIn("ready_to_cast = self.now_playing is not None", self.source)
        self.assertIn("self.cast_button.set_sensitive(ready_to_cast and online and not busy)", self.source)
        self.assertIn('self.cast_button.add_css_class("primary-action")', self.source)
        self.assertIn('self.open_button.add_css_class("primary-action")', self.source)

    def test_completed_encoder_does_not_disable_device_controls(self):
        # Ownership is retained while Chromecast drains the encoded HLS
        # playlist, even when the FFmpeg encoder has exited.
        self.assertIn(
            'active = bool(self.session is not None and self.session.state is not None) or self.external',
            self.source,
        )

    def test_responsiveness_is_not_sacrificed_for_styling(self):
        for snippet in (
            'self.page_scroller.set_child(self.page)',
            'responsive_layout.layout_for_size(width, height, self.cfg.get("density"))',
            'self.transport_grid.attach(button, column, row, 1, 1)',
            'self.action_grid.attach(child, col, row, 1, 1)',
        ):
            self.assertIn(snippet, self.source)
        self.assertNotIn("Gtk.Paned(", self.source)


    def test_auto_theme_schedule_boundaries(self):
        # SC-125 #134: night is 19:00-06:59 local time.
        for dark in (19, 23, 0, 6):
            self.assertTrue(ui_theme.is_dark_hour(dark), dark)
        for light in (7, 12, 18):
            self.assertFalse(ui_theme.is_dark_hour(light), light)

    def test_manual_scheme_overrides_auto_theme_and_schedule_reruns(self):
        control = (ROOT / "src/cast_control.py").read_text("utf-8")
        # A manual choice must disable the schedule so it actually applies.
        self.assertIn('window.cfg["auto_theme"] = False', control)
        # The schedule is re-evaluated while the app runs, not only at startup.
        self.assertIn("self._theme_tick", control)
        ui = (ROOT / "src/cast_ui.py").read_text("utf-8")
        self.assertIn("ui_theme.is_dark_hour(", ui)
        lifecycle = (ROOT / "src/cast_lifecycle.py").read_text("utf-8")
        self.assertIn("def _theme_tick", lifecycle)


if __name__ == "__main__":
    unittest.main()
