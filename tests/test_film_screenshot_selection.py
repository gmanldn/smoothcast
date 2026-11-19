"""SC-131: queued selection never changes the owned film screenshot or clock.

Executes the production GTK mixin methods with in-memory collaborators only.
Never creates a window or contacts a receiver.
"""
from __future__ import annotations

from pathlib import Path
import pathlib
from types import SimpleNamespace
import textwrap
from unittest import mock

from gui_source import main_window_methods


CURRENT = "/films/playing.mkv"
OTHER = "/films/queued.mkv"


def make_window():
    methods = main_window_methods()
    names = ("set_selection", "_on_queue_selected", "_screenshot")
    code = "class Window:\n" + "\n\n".join(
        textwrap.indent(textwrap.dedent(methods[name]), "    ")
        for name in names
    )
    jobs = []
    capture = mock.Mock(return_value=Path("/screens/active.png"))
    ns = {
        "pathlib": pathlib,
        "screenshot": SimpleNamespace(capture_frame=capture),
        "Async": SimpleNamespace(
            run=lambda work, done=None, failed=None: jobs.append((work, done, failed))
        ),
    }
    exec(compile(code, "<owned-screenshot>", "exec"), ns)
    w = ns["Window"]()
    w.queue = [CURRENT, OTHER]
    w.selected_index = 0
    w.now_playing = CURRENT
    w.media = SimpleNamespace(path=Path(CURRENT), video_stream_index=7)
    w.session = SimpleNamespace(state=SimpleNamespace(file=CURRENT))
    w.external = False
    w.busy = False
    w.cfg = {"screenshot_dir": "/screens"}
    w.tracker = SimpleNamespace(value=lambda: 83.25)
    w._preview_path = OTHER
    w._preview_position = 51.0
    w._local_video_path = None
    w._local_stream = lambda: None
    w.queue_list = mock.Mock()
    w.queue_list.get_row_at_index.return_value = mock.Mock()
    w.queue_search = SimpleNamespace(get_text=lambda: "")
    w.np_title = mock.Mock()
    w._refresh_controls = mock.Mock()
    w.toast = mock.Mock()
    w._rebuild_queue = mock.Mock()
    return w, jobs, capture


def run_capture(w, jobs):
    w._screenshot()
    assert len(jobs) == 1
    work, done, _ = jobs.pop()
    result = work()
    done(result)


def test_selecting_other_queue_row_does_not_change_cast_or_screenshot_target():
    w, jobs, capture = make_window()
    playing = w.media
    original_state = w.session.state
    row = SimpleNamespace(get_tooltip_text=lambda: OTHER)
    w._on_queue_selected(None, row)
    assert w.selected_index == 1
    assert w.media is playing
    assert w.session.state is original_state
    assert w.now_playing == CURRENT
    run_capture(w, jobs)
    capture.assert_called_once_with(
        Path(CURRENT), 83.25, Path("/screens"), video_stream_index=7
    )
    # Clicking the row again is not an explicit cast command.
    w.set_selection(OTHER)
    assert w.selected_index == 1
    assert w.media is playing
    assert w.now_playing == CURRENT
    assert w._rebuild_queue.call_count == 0


def test_unknown_cast_position_does_not_silently_capture_first_frame():
    w, jobs, capture = make_window()
    w.tracker.value = lambda: None
    w._screenshot()
    assert jobs == []
    capture.assert_not_called()
    assert w.toast.call_args.kwargs["error"] is True
    assert "position is unknown" in w.toast.call_args.args[0]


def test_mismatched_cast_metadata_does_not_capture_selected_queue_film():
    w, jobs, capture = make_window()
    w.session.state.file = OTHER
    w._screenshot()
    assert jobs == []
    capture.assert_not_called()
    assert "do not match" in w.toast.call_args.args[0]


def test_external_tv_content_is_not_captured_from_stale_local_media():
    w, jobs, capture = make_window()
    w.session = None
    w.external = True
    w._screenshot()
    assert jobs == []
    capture.assert_not_called()
    assert "another application" in w.toast.call_args.args[0]


def test_local_video_uses_decoder_timestamp_not_selected_queue_or_cast_clock():
    w, jobs, capture = make_window()
    w.session = None
    w._local_video_path = CURRENT
    w._local_stream = lambda: SimpleNamespace(get_timestamp=lambda: 74_250_000)
    run_capture(w, jobs)
    capture.assert_called_once_with(
        Path(CURRENT), 74.25, Path("/screens"), video_stream_index=7
    )


def test_invalid_local_decoder_timestamp_never_falls_back_to_frame_zero():
    w, jobs, capture = make_window()
    w.session = None
    w._local_video_path = CURRENT
    w._local_stream = lambda: SimpleNamespace(get_timestamp=lambda: -1)
    w._screenshot()
    assert jobs == []
    capture.assert_not_called()
    assert "local playback position is unknown" in w.toast.call_args.args[0]


def test_preview_source_timestamp_is_used_and_unrelated_preview_rejected():
    w, jobs, capture = make_window()
    w.session = None
    w._preview_path = CURRENT
    w._preview_position = 31.5
    run_capture(w, jobs)
    capture.assert_called_once_with(
        Path(CURRENT), 31.5, Path("/screens"), video_stream_index=7
    )
    w._preview_path = OTHER
    w._screenshot()
    assert jobs == []
    assert capture.call_count == 1
    assert "Select and preview" in w.toast.call_args.args[0]


def test_film_screenshot_source_check_executes_before_any_async_work():
    src = main_window_methods()["_screenshot"]
    assert src.index("state = self.session.state") < src.index("Async.run(")
    assert src.index("position = self.tracker.value()") < src.index("Async.run(")
    assert 'position is unknown' in src
