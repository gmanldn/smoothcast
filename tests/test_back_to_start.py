"""#171: Home invokes the back-to-start action."""
from __future__ import annotations

import cast_ui
from gui_shortcuts import installed_shortcuts


def test_home_shortcut_seeks_to_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(cast_ui.UiMixin, "_back_to_start", lambda self: calls.append(0.0))

    shortcuts = installed_shortcuts(monkeypatch=monkeypatch)
    shortcuts["Home"]()

    assert calls == [0.0]
