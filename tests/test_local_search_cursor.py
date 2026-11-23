"""Local FTS cursor safety: mocked queries, no SQLite or desktop (#554)."""
from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import search_engine  # noqa: E402


class LocalSearchCursorTests(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple[int, int]] = []
        self.ids = list(range(7))
        self.partial = False

        def run(conn, text, limit, offset, **kwargs):
            self.calls.append((limit, offset))
            return [{"id": i} for i in self.ids[offset:offset + limit + 1]], self.partial

        self.run_patch = mock.patch.object(search_engine, "run", side_effect=run)
        self.group_patch = mock.patch.object(
            search_engine, "group",
            side_effect=lambda rows: [{"items": rows}] if rows else [],
        )
        self.run_patch.start()
        self.group_patch.start()

    def tearDown(self):
        self.group_patch.stop()
        self.run_patch.stop()

    def items(self, **kwargs):
        page = search_engine.search(None, "film", **kwargs)
        return [i["id"] for group in page["groups"] for i in group["items"]], page["next"]

    def test_generated_cursors_preserve_sequential_paging(self):
        seen, cursor = [], None
        while True:
            items, nxt = self.items(limit=3, cursor=cursor)
            seen.extend(items)
            if not nxt:
                break
            cursor = nxt
        self.assertEqual(seen, self.ids)
        self.assertEqual(self.calls, [(3, 0), (3, 3), (3, 6)])

    def test_untrusted_cursors_cannot_crash_or_rewind_from_negative_offset(self):
        baseline, _ = self.items(limit=3)
        bad = [
            base64.urlsafe_b64encode(b"-1").decode(),
            base64.urlsafe_b64encode(b"01").decode(),
            base64.urlsafe_b64encode(b"200001").decode(),
            base64.urlsafe_b64encode(b"9" * 600).decode(),
            "?", "////", "MQ=", "MQ==x", "☃", 123, -1,
        ]
        for cursor in bad:
            with self.subTest(cursor=str(cursor)[:28]):
                self.assertEqual(self.items(limit=3, cursor=cursor)[0], baseline)
                self.assertEqual(self.calls[-1][1], 0)

    def test_expired_but_well_formed_cursor_restarts_from_first_page(self):
        cursor = base64.urlsafe_b64encode(b"500").decode()
        self.assertEqual(self.items(limit=3, cursor=cursor)[0], [0, 1, 2])
        self.assertEqual(self.calls, [(3, 500), (3, 0)])

    def test_partial_result_does_not_retry_expired_cursor(self):
        self.partial = True
        cursor = base64.urlsafe_b64encode(b"500").decode()
        self.assertEqual(self.items(limit=3, cursor=cursor)[0], [])
        self.assertEqual(self.calls, [(3, 500)])

    def test_nonfinite_or_wrong_limit_is_bounded_without_exception(self):
        for value in (None, float("nan"), float("inf"), float("-inf"), "oops"):
            with self.subTest(value=value):
                self.calls.clear()
                self.assertEqual(self.items(limit=value)[0], self.ids)
                self.assertEqual(self.calls, [(50, 0)])
        self.assertEqual(self.items(limit=-9)[0], [0])
        self.assertEqual(self.calls[-1], (1, 0))


if __name__ == "__main__":
    unittest.main()
