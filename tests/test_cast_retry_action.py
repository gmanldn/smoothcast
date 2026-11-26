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
import cast_failure_code
import cast_recovery
from gui_source import main_window_methods

NAMES = ("_cast_failed", "_retry_action", "_retry_cast", "_select_receiver")


def make_window(*, session=None, busy=False, closing=False, plan_kwargs=None):
    methods = main_window_methods()
    body = "\n".join(textwrap.indent(textwrap.dedent(methods[n]), "    ") for n in NAMES)
    ns = {"pathlib": pathlib, "cast_recovery": cast_recovery,
          "cast_failure_code": cast_failure_code, "LABELS": {
              "retry": "Try again", "alternate_encoding": "Convert and retry"},
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
            self.cfg = {"device": "Living Room"}
            self.model = SimpleNamespace(
                get_n_items=lambda: 2, get_string=lambda i: ("Living Room", "Kitchen")[i])
            self.device_dropdown = SimpleNamespace(
                get_model=lambda: self.model, set_selected=self._dropdown_selected)
            self.switch_allowed = True

        def _dropdown_selected(self, index):
            if self.switch_allowed:
                self.cfg["device"] = self.model.get_string(index)

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
    w._console.assert_any_call("Retrying cast at 2:05 (retry)")


def test_no_button_when_the_plan_has_nothing_to_offer_or_no_request_is_known():
    w = make_window()
    label = fail(w, "No supported format for this receiver")[2][0]
    assert label == "Continue on Kitchen"  # retry cannot help, another receiver can
    lonely = make_window()
    lonely.devices = []
    assert fail(lonely, "No supported format for this receiver")[2] is None  # nothing can help
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


def run_failure(w, message="Cast failed unexpectedly", mode="direct"):
    w._attempt_mode = mode
    return fail(w, message)


def test_button_advances_retry_then_convert_then_other_receiver():
    w = make_window()
    label, action = run_failure(w)[2]
    assert label == "Try again"
    action()                              # first retry (still direct)
    assert w._retry_in_flight is True and w._force_transcode_once is False
    label, action = run_failure(w)[2]     # (Living Room, direct) has now failed twice
    assert label == "Convert and retry"
    action()
    assert w._force_transcode_once is True
    label, action = run_failure(w, mode="transcode")[2]  # transcode failed once
    assert label == "Try again"
    action()
    assert w._force_transcode_once is False
    label, action = run_failure(w, mode="transcode")[2]  # transcode failed twice, nothing left here
    assert label == "Continue on Kitchen"
    action()
    assert w.cfg["device"] == "Kitchen"
    assert w._cast_path.call_count == 4 and w._cast_path.call_args.args[1] == 125.0


def test_other_receiver_is_not_cast_to_when_the_switch_is_refused():
    w = make_window()
    w._cast_tried = [("Living Room", "direct"), ("Living Room", "direct"),
                     ("Living Room", "transcode"), ("Living Room", "transcode")]
    label, action = run_failure(w, mode="transcode")[2]
    assert label == "Continue on Kitchen"
    w.switch_allowed = False                      # the existing handler refused (e.g. mid-cast)
    action()
    w._cast_path.assert_not_called()
    assert w.toasts[-1][0] == "Kitchen is not available right now"
    w2 = make_window()
    w2.model = SimpleNamespace(get_n_items=lambda: 1, get_string=lambda i: "Living Room")
    w2._cast_tried = list(w._cast_tried)
    run_failure(w2, mode="transcode")[2]
    assert w2._recovery_plan.primary is None or w2._recovery_plan.primary.kind != "alternate_target" \
        or w2.toasts[-1][2] is not None  # no discovered receiver => nothing to offer or a safe toast


def test_history_is_recorded_per_failure_and_bounded():
    w = make_window()
    for _ in range(40):
        run_failure(w)
    assert len(w._cast_tried) <= 16


def test_cast_path_forces_hls_once_and_resets_history_for_fresh_user_casts():
    body = main_window_methods()["_cast_path"]
    assert 'and not getattr(self, "_force_transcode_once", False)' in body
    assert body.index("self._force_transcode_once = False") > body.index("use_direct = (")
    assert '_attempt_mode = "direct" if use_direct else "transcode"' in body
    assert "if not getattr(self, \"_retry_in_flight\", False):\n            self._cast_tried = []" in body \
        or "self._cast_tried = []" in body
    assert body.index("self._cast_tried = []") < body.index("self._retry_in_flight = False")


def test_retry_mixin_is_registered_in_the_main_window():
    control = (Path(__file__).resolve().parents[1] / "src" / "cast_control.py").read_text("utf-8")
    assert "from cast_retry_ui import RetryMixin" in control and "RetryMixin, Adw.ApplicationWindow" in control


def test_toast_explains_why_for_convert_and_other_receiver_but_not_plain_retry():
    w = make_window()
    assert run_failure(w)[0] == "Cast failed: Cast failed unexpectedly"  # retry: no extra text
    w._cast_tried = [("Living Room", "direct")]
    message = run_failure(w)[0]
    assert message.startswith("Cast failed: Cast failed unexpectedly — Living Room could not play this")
    assert "converting it" in message
