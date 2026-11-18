"""Playlist parsing, atomic saving and GTK menu wiring regression checks."""
from __future__ import annotations

import ast
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import playlist_control

ROOT = Path(__file__).resolve().parents[1]


class PlaylistTests(unittest.TestCase):
    def test_round_trip_preserves_local_track_order(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            first, second = base / "one.mp4", base / "two.mkv"
            first.touch()
            second.touch()
            playlist = base / "smoothcast_playlist.m3u"
            playlist_control.save_playlist(playlist, [str(first), str(second)])
            tracks, skipped = playlist_control.load_playlist(playlist)
            self.assertEqual(tracks, [str(first), str(second)])
            self.assertEqual(skipped, 0)
            self.assertEqual(playlist.read_text().splitlines()[0], "#EXTM3U")

    def test_relative_entries_comments_urls_and_duplicates(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            video = base / "my film.mp4"
            video.touch()
            playlist = base / "playlist.m3u"
            playlist.write_text(
                "#EXTM3U\n#EXTINF:120,Movie\nmy film.mp4\n"
                "my film.mp4\nmissing.mkv\nhttps://example.com/stream\n",
                encoding="utf-8",
            )
            tracks, skipped = playlist_control.load_playlist(playlist)
            self.assertEqual(tracks, [str(video)])
            self.assertEqual(skipped, 2)

    def test_missing_or_invalid_playlist_has_clear_error(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            with self.assertRaises(playlist_control.PlaylistError):
                playlist_control.load_playlist(base / "missing.m3u")
            playlist = base / "large.m3u"
            with playlist.open("wb") as fh:
                fh.truncate(4 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(playlist_control.PlaylistError, "too large"):
                playlist_control.load_playlist(playlist)

    def test_empty_queue_rejected_without_overwriting_saved_playlist(self):
        with TemporaryDirectory() as folder:
            file = Path(folder) / "playlist.m3u"
            file.write_text("previous data")
            with self.assertRaises(playlist_control.PlaylistError):
                playlist_control.save_playlist(file, [])
            self.assertEqual(file.read_text(), "previous data")

    def test_search_matches_casefolded_terms_without_reordering(self):
        paths = [
            "/films/Drama/The Grand Film.mkv",
            "/films/Comedy/Grand Day Out.mp4",
            "/films/Drama/Another Film.mp4",
        ]
        self.assertEqual(
            [p for p in paths if playlist_control.matches_query(p, "grand drama")],
            [paths[0]],
        )
        self.assertEqual(
            [p for p in paths if playlist_control.matches_query(p, "FILM")],
            [paths[0], paths[2]],
        )
        self.assertTrue(all(playlist_control.matches_query(p, "   ") for p in paths))
        self.assertFalse(playlist_control.matches_query(paths[0], "missing title"))

    def test_queue_filter_preserves_original_index_and_focus_shortcut(self):
        source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
        self.assertIn("self.queue_list.set_filter_func(self._queue_row_matches)", source)
        self.assertIn("self.queue_list.invalidate_filter()", source)
        self.assertIn("row.set_tooltip_text(path)", source)
        self.assertIn('add("<Control>f", lambda: self.queue_search.grab_focus())', source)

    def test_actions_are_separate_and_load_uses_enqueue(self):
        source = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        window = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                      and n.name == "MainWindow")
        methods = {
            n.name: ast.get_source_segment(source, n)
            for n in window.body if isinstance(n, ast.FunctionDef)
        }
        self.assertIn("def _toggle_loop", methods["_toggle_loop"])
        self.assertIn('self.cfg["loop"]', methods["_toggle_loop"])
        self.assertNotIn('self.cfg["loop"]', methods["_load_playlist"])
        self.assertNotIn("self.queue_draw()", methods["_load_playlist"])
        self.assertIn("self._enqueue(additions)", methods["_load_playlist"])
        self.assertIn('simple("loop", lambda *a: self._window()._toggle_loop())', source)


if __name__ == "__main__":
    unittest.main()
