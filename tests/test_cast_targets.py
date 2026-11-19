"""SC-043 #52: receiver picker ordering, pinning and last-used tracking."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cast_targets


class CastTargetsTests(unittest.TestCase):
    def test_pinned_then_most_recent_then_discovery_order(self):
        ordered = cast_targets.ordered_names(
            ["Living Room", "Kitchen", "Bedroom"],
            ["192.168.1.50", "Kitchen"],
            ["Bedroom"],
            {"Kitchen": 100.0, "Living Room": 50.0},
        )
        self.assertEqual(
            ordered, ["Bedroom", "Kitchen", "Living Room", "192.168.1.50"]
        )
        self.assertEqual(len(ordered), len(set(ordered)))  # manual/discovery dedup

    def test_manual_entries_are_distinguishable(self):
        self.assertTrue(cast_targets.is_manual("192.168.1.50", ["192.168.1.50"]))
        self.assertFalse(cast_targets.is_manual("Living Room", ["192.168.1.50"]))

    def test_record_use_marks_now_and_drops_oldest(self):
        used = cast_targets.record_use({"A": 1.0}, "B", 99.0, limit=2)
        self.assertEqual(used, {"A": 1.0, "B": 99.0})
        used = cast_targets.record_use(
            {"A": 1.0, "B": 2.0, "C": 3.0}, "D", 4.0, limit=2
        )
        self.assertEqual(set(used), {"C", "D"})


if __name__ == "__main__":
    unittest.main()
