"""SC-114 #123: bounded timestamped watch history."""
from __future__ import annotations

import pathlib
import sys
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
            history, "/g.mkv", "completed", 0.0, 200.0, source="preview")
        self.assertEqual([e["path"] for e in both], ["/g.mkv", "/f.mkv"])
        self.assertEqual(both[0]["source"], "preview")

    def test_unknown_event_or_missing_path_is_ignored(self):
        self.assertEqual(watch_history.record([], "/f.mkv", "nope", 0.0, 1.0), [])
        self.assertEqual(watch_history.record([], "", "start", 0.0, 1.0), [])

    def test_history_is_bounded_newest_first(self):
        history = []
        for i in range(watch_history.LIMIT + 25):
            history = watch_history.record(history, f"/f{i}.mkv", "start", 0.0, float(i))
        self.assertEqual(len(history), watch_history.LIMIT)
        self.assertEqual(history[0]["path"], f"/f{watch_history.LIMIT + 24}.mkv")

    def test_clear_returns_empty(self):
        self.assertEqual(watch_history.clear(), [])


if __name__ == "__main__":
    unittest.main()
