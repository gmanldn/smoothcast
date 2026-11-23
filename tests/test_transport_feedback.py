"""#120: chapter, seek, speed and receiver-confirmed on-screen feedback."""
from __future__ import annotations
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock
from gui_source import main_window_methods


def _seek_window(seek_result=(True, '')):
    calls = []
    def run(work, done=None, failed=None, **_kwargs):
        calls.append('executed')
        try:
            result = work()
        except Exception as error:
            if failed:
                failed(str(error))
        else:
            if done:
                done(result)
    scope = {
        "fmt_time": lambda s: str(s),
        "Async": SimpleNamespace(run=run),
        "castctl": SimpleNamespace(is_seekable=lambda _: True, seek=lambda *_: seek_result),
        "dlna": SimpleNamespace(seek=lambda *_: None),
    }
    source = main_window_methods()["seek_to"]
    exec(compile("class Window:\n" + textwrap.indent(textwrap.dedent(source), "    "),
                 "<test-seek>", "exec"), scope)
    window = scope["Window"]()
    window.busy = False
    window.external = False
    window._closing = False
    window._preview_path = None
    window.now_playing = "/film.mkv"
    window.media = SimpleNamespace(duration=100)
    window.session = SimpleNamespace(mode='direct', state=SimpleNamespace(file='/film.mkv'))
    window.device_info = {}
    window.tracker = SimpleNamespace(duration=100, device_update=Mock())
    window.seekbar = SimpleNamespace(buffered=0, set_state=Mock())
    window._device = lambda: "Receiver"
    window._dlna_renderer = lambda _: None
    window.toast = Mock()
    window._refresh_controls = Mock()
    window._poll_device = Mock()
    return window, calls


def test_chapter_feedback_only_after_receiver_accepts_seek():
    success, calls = _seek_window()
    success.seek_to(12.5, feedback_label="Chapter: Opening")
    assert calls == ['executed']
    success.toast.assert_called_with("Chapter: Opening — 12.5")
    failed, _ = _seek_window((False, 'seek unsupported'))
    failed.seek_to(12.5, feedback_label="Chapter: Opening")
    failed.toast.assert_called_once_with('seek unsupported', error=True)


def test_plain_seek_remains_compatible_with_existing_handlers():
    window, _ = _seek_window()
    window.seek_to(5.0)
    window.toast.assert_called_once_with("Jumped to 5.0")


def test_chapter_hls_feedback_is_pending_until_restart_reports_success():
    window, _ = _seek_window()
    window.session.mode = "transcode"
    window._restart_at = Mock()
    window.seek_to(21, feedback_label="Chapter: Part II")
    window.toast.assert_called_once_with("Chapter: Part II — seeking…")
    window._restart_at.assert_called_once_with(window.session, 21, feedback_label="Chapter: Part II")


def test_speed_and_chapter_toasts_have_acknowledgement_wiring():
    source = main_window_methods()
    assert 'self.toast(f"Applying speed {speed:g}x…")' in source["_set_speed"]
    assert 'self.toast(f"Speed {speed:g}x applied")' in source["_restart_at"]
    assert 'self.toast(f"{feedback_label} — {fmt_time(target)}")' in source["_restart_at"]
    assert 'self.toast(f"Speed {speed}x — stream restarted")' not in source["_set_speed"]
    assert "if self.session is _session and not self._closing:" in source["_restart_at"]
