"""Behavioural access to the installed keyboard shortcuts without a window (#699).

``installed_shortcuts(window)`` runs the real ``_install_shortcuts`` against a stand-in window and
returns ``{accelerator: callback}``; calling a callback runs the same code a key press would.
"""
from __future__ import annotations

import cast_ui


class _Recorder(cast_ui.UiMixin):
    def __init__(self):
        self.registered_controller = None

    def __getattr__(self, name):
        return lambda *a, **kw: None

    def add_controller(self, controller):
        self.registered_controller = controller


def installed_shortcuts(window=None, monkeypatch=None) -> dict:
    window = window if window is not None else _Recorder()
    accels, callbacks = [], []
    gtk = cast_ui.Gtk
    real_parse, real_new = gtk.ShortcutTrigger.parse_string, gtk.CallbackAction.new
    gtk.ShortcutTrigger.parse_string = staticmethod(lambda accel: (accels.append(accel), real_parse(accel))[1])
    gtk.CallbackAction.new = staticmethod(lambda fn, *a: (callbacks.append(lambda: fn()), real_new(fn, *a))[1])
    window.add_controller = lambda controller: None
    try:
        cast_ui.UiMixin._install_shortcuts(window)
    finally:
        gtk.ShortcutTrigger.parse_string, gtk.CallbackAction.new = real_parse, real_new
    return dict(zip(accels, callbacks))
