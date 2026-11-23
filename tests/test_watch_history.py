"""SC-114 #123 and SC-033 #42: bounded, restart-safe watch-state records."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import watch_history


class WatchHistoryTests(unittest.TestCase):
    def test_record_prepends_and_tags_source(self):
        history = watch_history.record(
            [], "/f.mkv", "start", 12.0, 100.0, source="cast")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["event"], "start")
        self.assertEqual(history[0]["source"], "cast")
        self.assertEqual(history[0]["position"], 12.0)
        both = watch_history.record(
            history, "/f.mkv", "completed", 120.0, 200.0, source="preview")
        self.assertEqual([e["event"] for e in both], ["completed", "start"])

    def test_record_stores_duration_fingerprint_tracks_and_watched(self):
        history = watch_history.record(
            [], "/f.mkv", "stop", 300.0, 100.0, source="cast",
            duration=1200.0, fingerprint="123:456",
            tracks={"audio": 2, "subtitle": "English", "ignored": "x"},
        )
        entry = history[0]
        self.assertEqual(entry["duration"], 1200.0)
        self.assertEqual(entry["fingerprint"], "123:456")
        self.assertEqual(entry["tracks"], {"audio": 2, "subtitle": "English"})
        self.assertAlmostEqual(entry["watched"], 0.25)

    def test_invalid_optional_metadata_is_dropped_not_the_event(self):
        history = watch_history.record(
            [], "/f.mkv", "start", 10.0, 20.0,
            duration=-1, fingerprint="x" * 200,
            tracks={"audio": -1, "subtitle": "\x00bad"},
        )
        entry = history[0]
        self.assertIsNone(entry["duration"])
        self.assertIsNone(entry["fingerprint"])
        self.assertEqual(entry["tracks"], {})
        self.assertIsNone(entry["watched"])

    def test_unknown_event_or_missing_path_is_ignored(self):
        self.assertEqual(watch_history.record([], "/f.mkv", "nope", 0.0, 1.0), [])
        self.assertEqual(watch_history.record([], "", "start", 0.0, 1.0), [])

    def test_history_is_bounded_newest_first(self):
        history = []
        for i in range(watch_history.LIMIT + 5):
            history = watch_history.record(
                history, f"/f{i}.mkv", "start", float(i), float(i))
        self.assertEqual(len(history), watch_history.LIMIT)
        self.assertEqual(history[0]["path"], f"/f{watch_history.LIMIT + 4}.mkv")

    def test_clean_rejects_bad_entries_and_fills_optional_fields(self):
        cleaned = watch_history.clean([
            {"path": "/a.mkv", "event": "start", "source": "cast",
             "position": 1.0, "at": 2.0},
            {"path": "/b.mkv", "event": "bogus", "source": "cast",
             "position": 1.0, "at": 2.0},
            "not-a-dict",
        ])
        self.assertEqual([entry["path"] for entry in cleaned], ["/a.mkv"])
        self.assertIsNone(cleaned[0]["duration"])
        self.assertIsNone(cleaned[0]["fingerprint"])
        self.assertEqual(cleaned[0]["tracks"], {})
        self.assertIsNone(cleaned[0]["watched"])

    def test_latest_matches_path_and_optional_fingerprint(self):
        history = watch_history.record(
            [], "/f.mkv", "stop", 50.0, 1.0, fingerprint="one:1")
        history = watch_history.record(
            history, "/f.mkv", "stop", 90.0, 2.0, fingerprint="two:2")
        self.assertEqual(watch_history.latest_position(history, "/f.mkv"), 90.0)
        self.assertEqual(
            watch_history.latest_position(history, "/f.mkv", "one:1"), 50.0)
        self.assertIsNone(
            watch_history.latest_position(history, "/f.mkv", "missing:0"))
        self.assertIsNone(watch_history.latest_position(history, "/other.mkv"))

    def test_fingerprint_tracks_stat_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "media.mkv"
            path.write_bytes(b"first")
            first = watch_history.fingerprint(path)
            self.assertIsNotNone(first)
            path.write_bytes(b"second-longer")
            os.utime(path, ns=(1, 1))
            self.assertNotEqual(first, watch_history.fingerprint(path))
            self.assertIsNone(watch_history.fingerprint(path.with_suffix(".missing")))

    def test_clear(self):
        self.assertEqual(watch_history.clear(), [])


if __name__ == "__main__":
    unittest.main()
