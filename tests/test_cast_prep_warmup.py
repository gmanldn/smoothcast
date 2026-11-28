"""The FFmpeg version query is paid at window start, not on the first cast."""
from types import SimpleNamespace

import pytest

try:
    import cast_ui_timers
except ImportError as exc:  # no usable PyGObject in this environment
    pytest.skip(f"GTK bindings unavailable: {exc}", allow_module_level=True)
import streamer


def test_window_timers_warm_the_ffmpeg_version_check_off_thread(monkeypatch):
    queued = []
    monkeypatch.setattr(cast_ui_timers.Async, "run", lambda fn, *a, **kw: queued.append(fn))
    monkeypatch.setattr(cast_ui_timers.GLib, "timeout_add", lambda *a, **kw: 0)
    monkeypatch.setattr(cast_ui_timers.GLib, "timeout_add_seconds", lambda *a, **kw: 0)
    class Window(SimpleNamespace):
        def __getattr__(self, name):                 # every other window method is a harmless no-op
            return lambda *a, **kw: None

    window = Window()

    cast_ui_timers.UiTimerMixin._start_window_timers(window)

    assert streamer.require_compatible_ffmpeg in queued
