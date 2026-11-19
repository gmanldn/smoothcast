"""Preferences: pure mapping and source wiring, with no GTK or display.

Running these tests never opens SmoothCast, a receiver, or a window.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

import preference_choices

ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / "src" / name).read_text(encoding="utf-8")


class PreferenceChoiceTests(unittest.TestCase):
    def test_options_roundtrip_and_fallback(self):
        for key, options in preference_choices.OPTIONS.items():
            with self.subTest(key=key):
                self.assertEqual(preference_choices.labels(key),
                                 [label for label, _ in options])
                for index, (_label, value) in enumerate(options):
                    self.assertEqual(preference_choices.selected_index(key, value), index)
                    self.assertEqual(preference_choices.selected_value(key, index), value)
                self.assertEqual(preference_choices.selected_index(key, object()), 0)

    def test_reject_invalid_index_even_boolean(self):
        for key in preference_choices.OPTIONS:
            for index in (-1, 999, True, "1", 1.0):
                with self.subTest(key=key, index=index):
                    with self.assertRaises(ValueError):
                        preference_choices.selected_value(key, index)

    def test_index_order_matches_existing_player_controls(self):
        # Direct handlers receive Gtk.DropDown indices, not raw text.
        self.assertEqual(
            [v for _label, v in preference_choices.OPTIONS["quality"]],
            ["high", "balanced", "saver"],
        )
        self.assertEqual(
            [v for _label, v in preference_choices.OPTIONS["audio"]],
            ["original", "dialogue", "night"],
        )
        self.assertEqual(
            [v for _label, v in preference_choices.OPTIONS["rotation"]],
            [0, 90, 180, 270],
        )
        self.assertEqual(
            [v for _label, v in preference_choices.OPTIONS["subs"]],
            ["off", "auto", "pick", "embedded"],
        )

    def test_gtk_module_is_parsable_without_importing_gtk(self):
        ast.parse(source("preferences_ui.py"))

    def test_registered_and_accessible_preferences(self):
        control = source("cast_control.py")
        player = source("cast_ui.py")
        package = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('simple("preferences", lambda *a: self._window().action_preferences())', control)
        self.assertIn('self.set_accels_for_action("app.preferences", ["<Control>comma"])', control)
        self.assertIn('menu.append("Preferences…", "app.preferences")', player)
        self.assertIn('preferences_button.connect("clicked", lambda _button: self.action_preferences())', player)
        self.assertIn('inline = Gtk.Expander(label="Show inline playback controls")', player)
        self.assertIn('self.keep_switch = self._switch_row(', player)
        for item in ('"preferences_ui"', '"preference_choices"'):
            self.assertIn(item, package)

    def test_settings_are_searchable_and_reuse_original_handlers(self):
        ui = source("preferences_ui.py")
        for snippet in (
            "Adw.PreferencesWindow",
            "self.set_search_enabled(True)",
            "self.set_default_size(660, 520)",
            "self.sync_from_owner()",
            "self.owner.app.scheme_action.activate",
            "getattr(self.owner, widgets[key]).set_selected",
            "getattr(owner, widgets[key]).set_active",
            "self.owner.audio_track_dropdown.set_selected",
            "self.owner.embedded_dropdown.set_selected",
            "self.owner._subs_file_chosen(dialog, result)",
            "self.owner.gain_spin.set_value",
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, ui)
        self.assertNotIn("threading.Thread(", ui)
        self.assertNotIn("castctl.", ui)
        self.assertNotIn("dlna.", ui)


if __name__ == "__main__":
    unittest.main()
