"""#13: a failed cast offers ONE safe 'Try again' that re-enters the normal cast path."""
from __future__ import annotations

import pathlib
from pathlib import Path
import sys
import textwrap
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cast_recovery
from gui_source import main_window_methods

NAMES = ("_cast_failed", "_retry_action", "_retry_cast")


def make_window(*, session=None, busy=False, closing=False, plan_kwargs=None):
    methods = main_window_methods()
    body = "\n".join(textwrap.indent(textwrap.dedent(methods[n]), "    ") for n in NAMES)
    ns = {"pathlib": pathlib, "cast_recovery": cast_recovery,
          "fmt_time": cast_recovery.format_position,
          "reliability_metrics": SimpleNamespace(fail_attempt=lambda *_a: None,
                                                 finish_active=lambda *_a: None),
          "Async": SimpleNamespace(run=lambda *_a, **_k: None)}
    exec(compile("class H:\n" + body, "<retry>", "exec"), ns)

    class Window(ns["H"]):
        def __init__(self):
            self.session, self.busy, self._closing = session, busy, closing
            self._dlna_cancel = None
            self._finished_handled = False
            self.tracker = SimpleNamespace(value=lambda: 125.0, clear=mock.Mock())
            self.devices = [SimpleNamespace(name="Kitchen")]
            self.device_info = {"duration": 3600}
            self.toasts = []
            self._console = mock.Mock()
            self._cast_path = mock.Mock(return_value=None)
            self._stop_monitor = mock.Mock()
            self._set_levels_hint = mock.Mock()
            self._refresh_controls = mock.Mock()
            self._notify = mock.Mock()

        def toast(self, message, *, error=False, action=None):
            self.toasts.append((message, error, action))

        def _device(self):
            return "Living Room"

    return Window()


def fail(window, message="Receiver is offline", path="/media/film.mkv"):
    window._last_cast_path = path
    window._cast_failed(message)
    return window.toasts[-1]


def test_failure_toast_gets_one_try_again_button_with_the_saved_place():
    w = make_window()
    message, error, action = fail(w)
    assert message == "Cast failed: Receiver is offline" and error is True
    label, callback = action
    assert label == "Try again"
    callback()
    w._cast_path.assert_called_once_with(pathlib.Path("/media/film.mkv"), 125.0)  # normal entry, saved place
    w._console.assert_any_call("Retrying cast at 2:05")


def test_no_button_when_the_plan_has_no_plain_retry_or_no_request_is_known():
    w = make_window()
    assert fail(w, "No supported format for this receiver")[2] is None  # retry cannot help
    w2 = make_window()
    w2._cast_failed("Receiver is offline")  # no remembered request
    assert w2.toasts[-1][2] is None


def test_a_newer_failure_invalidates_the_older_button():
    w = make_window()
    old = fail(w)[2][1]
    fail(w)
    old()
    w._cast_path.assert_not_called()
    assert w.toasts[-1][0] == "Playback changed; not retrying automatically"


@pytest.mark.parametrize("state", [
    dict(busy=True), dict(closing=True),
    dict(session=SimpleNamespace(active=lambda: True)),
])
def test_retry_never_interrupts_other_work(state):
    w = make_window()
    action = fail(w)[2][1]
    for key, value in state.items():
        setattr(w, {"closing": "_closing"}.get(key, key), value)
    action()
    w._cast_path.assert_not_called()
    assert "not retrying" in w.toasts[-1][0]


def test_inactive_leftover_session_does_not_block_a_retry():
    w = make_window(session=SimpleNamespace(active=lambda: False))
    fail(w)[2][1]()
    w._cast_path.assert_called_once()


def test_toast_api_builds_one_button_and_callback_without_gtk():
    source = main_window_methods()["toast"]
    assert 'toast.set_button_label(label)' in source and '"button-clicked"' in source
    assert "action=None" in source


def test_cast_path_records_the_request_only_after_guards_pass():
    body = main_window_methods()["_cast_path"]
    assert body.index("self._last_cast_path = path") > body.index("Choose a room receiver before casting")
