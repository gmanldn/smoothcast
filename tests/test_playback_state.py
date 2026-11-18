"""Regression tests for seeked HLS progress and Chromecast completion."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gui_source import combined_source

from playback_state import absolute_encoded_position, playback_ended, direct_session_matches, start_offset


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

    def test_explicit_zero_seek_never_resumes_previous_position(self):
        self.assertEqual(start_offset(0.0, 658.0), 0.0)
        self.assertEqual(start_offset(12.5, 658.0), 12.5)
        self.assertEqual(start_offset(None, 658.0), 658.0)
        self.assertEqual(start_offset(None, "658.5"), 658.5)

    def test_invalid_resume_values_fail_safe_to_start(self):
        for value in (None, "", "not-a-number", float("inf"), -10, "nan"):
            with self.subTest(value=value):
                self.assertEqual(start_offset(None, value), 0.0)

    def test_queue_auto_next_starts_at_zero_not_saved_resume(self):
        source = combined_source()
        self.assertIn("self._cast_path(next_path, 0.0)", source)
        self.assertIn("self._cast_path(pathlib.Path(self.now_playing), target)", source)
        self.assertIn("self._cast_path(path, None)", source)
        self.assertIn('offset = playback_state.start_offset(', source)

    def test_only_device_completion_advances_the_queue(self):
        self.assertTrue(playback_ended("PLAYING", "IDLE", has_session=True, busy=False))
        self.assertTrue(playback_ended("PAUSED", "IDLE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "OFFLINE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=True, busy=True))
        self.assertFalse(playback_ended("IDLE", "IDLE", has_session=True, busy=False))
        self.assertFalse(playback_ended("PLAYING", "IDLE", has_session=False, busy=False))


if __name__ == "__main__":
    unittest.main()
