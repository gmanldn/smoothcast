"""Headless screenshot source-clock tests: no GTK or FFmpeg subprocess."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pathlib
import textwrap
import unittest

from gui_source import main_window_methods
import screenshot as screenshot_module


FILM = str(Path("/fixtures/film.mkv"))


class FakeAsync:
    @staticmethod
    def run(work, done=None, failed=None):
        try:
            result = work()
            if done:
                done(result)
        except Exception as exc:
            if failed:
                failed(str(exc))


class CaptureClockTests(unittest.TestCase):
    def make_window(self):
        invocations = []
        screenshot = SimpleNamespace(
            capture_frame=lambda source, position, output, *, video_stream_index:
                invocations.append((str(source), position, video_stream_index)) or Path("saved.png")
        )
        namespace = {"Async": FakeAsync, "pathlib": pathlib, "screenshot": SimpleNamespace(
            capture_frame=screenshot.capture_frame,
            owned_frame_time=screenshot_module.owned_frame_time,
            FramePositionError=screenshot_module.FramePositionError,
        )}
        code = main_window_methods()["_screenshot"]
        exec(compile("class Window:\n" + textwrap.indent(code, "    "),
                     "<screenshot-window>", "exec"), namespace)
        win = namespace["Window"]()
        win.media = SimpleNamespace(path=Path(FILM),
                                    video_stream_index=3)
        win.cfg = {"screenshot_dir": "/virtual/screens"}
        win._preview_path = FILM
        win._preview_position = 42.0
        win._local_video_path = None
        win._local_stream = lambda: None
        win.session = None
        win.external = False
        win.tracker = SimpleNamespace(value=lambda: 155.0)
        notices = []
        win.toast = lambda msg, error=False: notices.append((msg, error))
        return win, invocations, notices

    def test_scrubbed_still_uses_local_preview_position_not_tv_tracker(self):
        win, calls, _ = self.make_window()
        win._screenshot()
        self.assertEqual(calls, [(str(Path(FILM)), 42.0, 3)])

    def test_paused_embedded_player_uses_actual_decoder_timestamp(self):
        win, calls, _ = self.make_window()
        win._local_video_path = FILM
        win._local_stream = lambda: SimpleNamespace(get_timestamp=lambda: 91_000_000)
        win._screenshot()
        self.assertEqual(calls, [(str(Path(FILM)), 91.0, 3)])

    def test_owned_cast_uses_receiver_clock_even_if_local_preview_is_stale(self):
        win, calls, _ = self.make_window()
        win.session = SimpleNamespace(state=SimpleNamespace(file=FILM))
        win._local_video_path = FILM
        win._local_stream = lambda: SimpleNamespace(get_timestamp=lambda: 91_000_000)
        win.tracker = SimpleNamespace(value=lambda: 25.25)
        win._screenshot()
        self.assertEqual(calls, [(str(Path(FILM)), 25.25, 3)])

    def test_no_media_or_foreign_tv_cast_cannot_capture_unrelated_content(self):
        win, calls, notices = self.make_window()
        win.external = True
        win._screenshot()
        self.assertEqual(calls, [])
        self.assertTrue(notices[-1][1])
        win.external = False
        win.media = None
        win._screenshot()
        self.assertEqual(calls, [])
        self.assertTrue(notices[-1][1])

    def test_unknown_local_decoder_timestamp_falls_back_to_selected_still(self):
        win, calls, _ = self.make_window()
        win._local_video_path = FILM
        win._local_stream = lambda: SimpleNamespace(get_timestamp=lambda: -1)
        win._screenshot()
        self.assertEqual(calls, [(str(Path(FILM)), 42.0, 3)])


if __name__ == "__main__":
    unittest.main()
