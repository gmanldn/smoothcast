"""Regress authoritative source-file timing under non-1× playback.

These tests run without GTK, catt, FFmpeg or a connected Chromecast.
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import position_tracker
from playback_state import absolute_encoded_position


class PlaybackRateTests(unittest.TestCase):
    def test_encoder_and_device_clock_map_to_source_time(self):
        # Seeking the source to 45s restarts HLS presentation timestamps at 0.
        self.assertEqual(absolute_encoded_position(45, 10, 120, speed=2), 65)
        self.assertEqual(absolute_encoded_position(45, 10, 120, speed=0.5), 50)
        self.assertEqual(absolute_encoded_position(115, 10, 120, speed=2), 120)

    def test_estimated_position_advances_at_speed_and_clamps(self):
        with mock.patch.object(position_tracker.time, "monotonic", return_value=10):
            tracker = position_tracker.PositionTracker()
            tracker.start(20, 100, True, rate=2)
        self.assertAlmostEqual(tracker.value(now=15), 30)
        self.assertEqual(tracker.value(now=60), 100)

    def test_device_position_advances_at_speed(self):
        with mock.patch.object(position_tracker.time, "monotonic", return_value=10):
            tracker = position_tracker.PositionTracker()
            tracker.start(20, 100, True, rate=2)
            tracker.device_update(42, 100, rate=2)
        self.assertAlmostEqual(tracker.value(now=15), 52)

    def test_device_position_stays_frozen_during_pause(self):
        with mock.patch.object(position_tracker.time, "monotonic", return_value=10):
            tracker = position_tracker.PositionTracker()
            tracker.start(20, 100, True, rate=2)
            tracker.device_update(42, 100, rate=2)
        with mock.patch.object(position_tracker.time, "monotonic", return_value=15):
            tracker.set_state(False)
        self.assertEqual(tracker.value(now=27), 42)
        with mock.patch.object(position_tracker.time, "monotonic", return_value=27):
            tracker.set_state(True)
        self.assertEqual(tracker.value(now=30), 48)  # only 3 real seconds played

    def test_rebase_preserves_rate_and_clear_resets(self):
        with mock.patch.object(position_tracker.time, "monotonic", return_value=10):
            tracker = position_tracker.PositionTracker()
            tracker.start(30, 120, True, rate=1.5)
            tracker.rebase(60)
        self.assertAlmostEqual(tracker.rate, 1.5)
        self.assertAlmostEqual(tracker.value(now=12), 63)
        tracker.clear()
        self.assertFalse(tracker.known)
        self.assertEqual(tracker.rate, 1.0)


if __name__ == "__main__":
    unittest.main()
