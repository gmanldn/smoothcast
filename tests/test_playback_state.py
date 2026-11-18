"""Regression tests for seeked HLS progress and Chromecast completion."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from playback_state import absolute_encoded_position, playback_ended, direct_session_matches


class PlaybackStateTests(unittest.TestCase):
    def test_seeked_progress_is_absolute(self):
        self.assertEqual(absolute_encoded_position(600, 4.5, 1000), 604.5)
        self.assertEqual(absolute_encoded_position(600, 500, 900), 900)
        self.assertEqual(absolute_encoded_position(0, 4.5, 1000), 4.5)
        self.assertIsNone(absolute_encoded_position(600, None))

    def test_nonunit_speed_maps_hls_time_to_original_media(self):
        self.assertEqual(absolute_encoded_position(45, 10, 120, speed=2.0), 65)
        self.assertEqual(absolute_encoded_position(90, 20, 120, speed=2.0), 120)
        self.assertEqual(absolute_encoded_position(45, 10, 120, speed=0.5), 50)
        self.assertIsNone(absolute_encoded_position(0, 5, 100, speed=0))

    def test_saved_direct_session_requires_live_matching_device(self):
        self.assertFalse(direct_session_matches(None, "Film"))
        self.assertFalse(direct_session_matches({"player_state": "IDLE", "title": "Film"}, "Film"))
        self.assertFalse(direct_session_matches({"player_state": "PLAYING", "title": "Other"}, "Film"))
        self.assertTrue(direct_session_matches({"player_state": "PAUSED", "title": "Film"}, "Film"))
        self.assertTrue(direct_session_matches({"player_state": "BUFFERING", "title": ""}, "Film"))

    def test_only_device_completion_advances_the_queue(self):
        self.assertTrue(playback_ended("PLAYING", "IDLE", has_session=True, busy=False))
        self.assertTrue(playback_ended("PAUSED", "IDLE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "OFFLINE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=True, busy=True))
        self.assertFalse(playback_ended("IDLE", "IDLE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=False, busy=False))


if __name__ == "__main__":
    unittest.main()
