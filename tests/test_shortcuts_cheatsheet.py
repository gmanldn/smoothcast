"""SC-116 #125: the cheatsheet covers the real installed accelerators."""
from __future__ import annotations

from gui_shortcuts import installed_shortcuts
from cast_lifecycle_actions import desktop_shortcuts


def test_cheatsheet_lists_installed_shortcuts():
    installed = {key.lower() for key in installed_shortcuts()}
    documented = {key.lower() for key, _label in desktop_shortcuts()}

    assert {"p", "n", "comma", "period", "home", "space", "k", "j", "l", "m"} <= installed
    assert {key for key in installed if len(key) == 1 and key.isalpha()} <= documented
    assert {"comma", "period", "home", "<control>f", "<control>w", "<control>q"} <= documented
