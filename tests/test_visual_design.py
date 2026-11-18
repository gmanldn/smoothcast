"""GTK-independent checks for SmoothCast's visual system and live UI wiring.

These exercise structural and contrast invariants in CI without requiring a
Chromecast, X11/Wayland display or a PyGObject installation.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import ui_theme


def luminance(value: str) -> float:
    channels = [int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return sum(x * k for x, k in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(fg: str, bg: str) -> float:
    light, dark = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class VisualDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "src" / "cast_control.py").read_text("utf-8")
        cls.theme = ui_theme.CSS.decode("utf-8")

    def test_gtk_code_and_theme_are_valid_python(self):
        for name in ("cast_control.py", "ui_theme.py"):
            path = ROOT / "src" / name
            ast.parse(path.read_text("utf-8"), filename=str(path))

    def test_high_contrast_text_across_canonical_surfaces(self):
        for background in ("canvas", "surface", "surface_raised"):
            for foreground in ("text", "muted"):
                with self.subTest(background=background, foreground=foreground):
                    self.assertGreaterEqual(
                        contrast(ui_theme.PALETTE[foreground],
                                 ui_theme.PALETTE[background]), 4.5)

    def test_theme_keeps_semantic_control_hierarchy(self):
        for selector in (".hero-card", ".hero-title", ".big-play", ".primary-action",
                         ".settings-card", ".setting-group", ".device-badge",
                         ".empty-state", ".detail-section", ".console-idle"):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.theme)
        self.assertIn(".dim-label {", self.theme)
        self.assertIn("opacity: 0.93", self.theme)

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
            'responsive_layout.layout_for_size(width, height)',
            'self.transport_grid.attach(button, column, row, 1, 1)',
            'self.action_grid.attach(child, col, row, 1, 1)',
        ):
            self.assertIn(snippet, self.source)
        self.assertNotIn("Gtk.Paned(", self.source)


if __name__ == "__main__":
    unittest.main()
