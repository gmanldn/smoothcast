"""SC-116 #125: the keyboard cheatsheet must match the installed accelerators."""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gui_source import main_window_methods
import shortcut_map


class ShortcutsCheatsheetTests(unittest.TestCase):
    def test_documented_keys_are_actually_installed(self):
        installed = {
            a.lower()
            for a in re.findall(r'add\("([^"]+)"', main_window_methods()["_install_shortcuts"])
        }
        # P/N were documented but never bound before this fix.
        for key in ("p", "n", "comma", "period", "home", "space", "k", "j", "l", "m", "s"):
            self.assertIn(key, installed, key)

    def test_cheatsheet_lists_every_installed_letter_shortcut(self):
        methods = main_window_methods()
        documented = {
            a.lower()
            for a in re.findall(r'\("([^"]+)", "', methods["action_shortcuts"])
        }
        installed = {
            a.lower()
            for a in re.findall(r'add\("([^"]+)"', methods["_install_shortcuts"])
        }
        documented.update(key.lower() for key, _title in shortcut_map.desktop_labels())
        installed_letters = {a for a in installed if len(a) == 1 and a.isalpha()}
        self.assertTrue(installed_letters.issubset(documented), installed_letters - documented)
        for key in ("comma", "period", "home", "<control>f", "<control>w", "<control>q"):
            self.assertIn(key, documented, key)

    def test_cheatsheet_documents_preview_versus_tv(self):
        source = main_window_methods()["action_shortcuts"]
        self.assertIn("preview", source.lower())
        self.assertIn("tv", source.lower())


if __name__ == "__main__":
    unittest.main()
