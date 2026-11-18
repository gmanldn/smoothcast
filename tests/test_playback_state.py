"""Regression tests for seeked HLS progress and Chromecast completion."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playback_state import absolute_encoded_position, playback_ended


class PlaybackStateTests(unittest.TestCase):
    def test_seeked_progress_is_absolute(self):
        self.assertEqual(absolute_encoded_position(600, 4.5, 1000), 604.5)
        self.assertEqual(absolute_encoded_position(600, 500, 900), 900)
        self.assertEqual(absolute_encoded_position(0, 4.5, 1000), 4.5)
        self.assertIsNone(absolute_encoded_position(600, None))

    def test_only_device_completion_advances_the_queue(self):
        self.assertTrue(playback_ended("PLAYING", "IDLE", has_session=True, busy=False))
        self.assertTrue(playback_ended("PAUSED", "IDLE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "OFFLINE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=True, busy=True))
        self.assertFalse(playback_ended("IDLE", "IDLE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=False, busy=False))


if __name__ == "__main__":
    unittest.main()
