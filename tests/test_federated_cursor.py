"""Bounded federated-search cursor parsing: real search, no GTK/LAN (#552)."""
from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import federated_search  # noqa: E402


def _record(number: int) -> dict:
    title = f"Film {number:03}"
    return {
        "content_key": f"key-{number:03}", "kind": "video",
        "title": title, "sort_title": title.casefold(),
        "year": None, "artist": None, "album": None, "duration": 120,
    }


def _items(page: dict) -> list[str]:
    return [
        item["id"] for group in page["groups"]
        for item in group["items"]
    ]


class SearchCursorTests(unittest.TestCase):
    def setUp(self):
        self.svc = federated_search.FederatedSearch(
            lambda text, limit: [_record(i) for i in range(12)],
            lambda text, limit: [],
            lambda: {},
            lambda *args: (200, {"entries": []}),
        )

    def tearDown(self):
        self.svc.close()

    def test_valid_cursor_continues_without_repeats(self):
        first = self.svc.search("film", limit=5)
        second = self.svc.search("film", limit=5, cursor=first["next"])
        third = self.svc.search("film", limit=5, cursor=second["next"])
        self.assertEqual(
            _items(first) + _items(second) + _items(third),
            [f"key-{i:03}" for i in range(12)],
        )
        self.assertIsNone(third["next"])

    def test_negative_malformed_noncanonical_or_oversized_restart_at_zero(self):
        baseline = _items(self.svc.search("film", limit=3))
        cursors = [
            base64.urlsafe_b64encode(b"-1").decode(),
            base64.urlsafe_b64encode(b"01").decode(),
            base64.urlsafe_b64encode(b"500").decode(),
            base64.urlsafe_b64encode(b"9" * 500).decode(),
            "!!!!", "////", "MQ=", "MQ==x", "é", 1, -3,
        ]
        for cursor in cursors:
            with self.subTest(cursor=str(cursor)[:32]):
                self.assertEqual(
                    _items(self.svc.search("film", limit=3, cursor=cursor)),
                    baseline,
                )

    def test_nonfinite_and_invalid_limits_are_safe_and_bounded(self):
        for limit in (float("nan"), float("inf"), float("-inf"), None, "wrong"):
            with self.subTest(limit=limit):
                page = self.svc.search("film", limit=limit)
                self.assertEqual(_items(page), [f"key-{i:03}" for i in range(12)])
                self.assertIsNone(page["next"])
        self.assertEqual(len(_items(self.svc.search("film", limit=-999))), 1)
        self.assertEqual(len(_items(self.svc.search("film", limit=999999))), 12)


if __name__ == "__main__":
    unittest.main()
