"""Historical feature verification suite (SC-132 #141).

Confirms rotation, playlist round-trip, multi-file open, queue search, theatre
mode, sleep timer, auto-shutdown and URL cast actually work — using the real
pure logic, an executable queue handler, and source/AST wiring checks. No GTK or
display is used.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gui_source import main_window_methods
import playback_state
import playlist_control
import streamer
import url_control


class HistoricalFeatureTests(unittest.TestCase):
    def test_rotation_chain(self):
        self.assertEqual(streamer.rotation_filters(0), [])
        for degrees in (90, 180, 270):
            self.assertTrue(streamer.rotation_filters(degrees), degrees)
        # An unsupported angle normalises to no rotation, never a crash.
        self.assertEqual(streamer.rotation_filters(450), [])
        self.assertEqual(streamer.rotation_filters("sideways"), [])

    def test_playlist_round_trip(self):
        with tempfile.TemporaryDirectory() as work:
            root = pathlib.Path(work).resolve()
            first = root / "a.mp4"
            first.write_bytes(b"x")
            second = root / "b.mp4"
            second.write_bytes(b"x")
            playlist = root / "list.m3u"
            playlist_control.save_playlist(playlist, [str(first), str(second)])
            loaded, skipped = playlist_control.load_playlist(playlist)
            self.assertEqual(loaded, [str(first), str(second)])
            self.assertEqual(skipped, 0)

    def test_multi_file_open_selects_first_and_queues_the_rest(self):
        namespace = {"playlist_control": playlist_control}
        code = "class M:\n" + textwrap.indent(
            textwrap.dedent(main_window_methods()["open_paths"]), "    ")
        exec(compile(code, "<open-paths>", "exec"), namespace)

        class Fake(namespace["M"]):
            def __init__(self):
                self.selected = []
                self.enqueued = []
                self.presented = 0

            def set_selection(self, path):
                self.selected.append(path)

            def _enqueue(self, paths):
                self.enqueued.append(list(paths))

            def present(self):
                self.presented += 1

        fake = Fake()
        fake.open_paths(["/a.mp4", "/b.mp4", "/c.mp4"])
        self.assertEqual(fake.selected, ["/a.mp4"])
        self.assertEqual(fake.enqueued, [["/b.mp4", "/c.mp4"]])
        self.assertEqual(fake.presented, 1)

    def test_queue_search_filters_without_reordering(self):
        search = main_window_methods()["_on_queue_search"]
        self.assertIn("queue_search", search)
        self.assertNotIn("self.queue.sort", search)
        self.assertNotIn("self.queue =", search)
        self.assertNotIn("self.queue.remove", search)

    def test_theatre_mode_toggles_maximise(self):
        theatre = main_window_methods()["_toggle_theater"]
        self.assertIn("is_maximized()", theatre)
        self.assertIn("maximize()", theatre)
        self.assertIn("unmaximize()", theatre)

    def test_auto_shutdown_toggles_and_persists(self):
        shutdown = main_window_methods()["_toggle_auto_shutdown"]
        self.assertIn('self.cfg["auto_shutdown"]', shutdown)
        self.assertIn("save_config(self.cfg)", shutdown)

    def test_sleep_timer_deadline(self):
        self.assertEqual(playback_state.sleep_deadline(100.0, 0), 0.0)
        self.assertEqual(playback_state.sleep_deadline(100.0, 30), 100.0 + 1800)
        self.assertTrue(playback_state.timer_expired(50.0, 100.0))
        self.assertFalse(playback_state.timer_expired(200.0, 100.0))
        self.assertFalse(playback_state.timer_expired(0.0, 100.0))

    def test_url_cast_validates_and_is_wired(self):
        self.assertEqual(
            url_control.validate_media_url("https://example.com/film.mp4"),
            "https://example.com/film.mp4",
        )
        for bad in ("file:///etc/passwd", "ftp://host/x", "https://u:p@host/x"):
            with self.assertRaises(ValueError):
                url_control.validate_media_url(bad)
        self.assertIn("validate_media_url", main_window_methods()["_cast_remote_url"])


if __name__ == "__main__":
    unittest.main()
