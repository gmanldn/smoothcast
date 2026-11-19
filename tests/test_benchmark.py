"""SC-048 #57: playback-quality benchmark recommendation and probe."""
from __future__ import annotations

import pathlib
import shutil
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import benchmark


class BenchmarkTests(unittest.TestCase):
    def test_parse_fps_takes_last_positive_value(self):
        text = "frame= 30 fps= 30.0 q=28\nframe= 120 fps= 59.5 q=27\n"
        self.assertEqual(benchmark.parse_fps(text), 59.5)
        self.assertIsNone(benchmark.parse_fps("no progress here"))
        self.assertIsNone(benchmark.parse_fps("fps= 0"))
        self.assertIsNone(benchmark.parse_fps(None))

    def test_recommend_tiers_and_realtime(self):
        self.assertEqual(benchmark.recommend(90.0, 30.0)["tier"], "4K")
        self.assertEqual(benchmark.recommend(35.0, 30.0)["tier"], "1080p")
        self.assertEqual(benchmark.recommend(22.0, 30.0)["tier"], "720p")
        self.assertFalse(benchmark.recommend(22.0, 30.0)["realtime"])
        self.assertTrue(benchmark.recommend(35.0, 30.0)["realtime"])
        # Unknown measurement is conservative and never real-time.
        low = benchmark.recommend(None, 30.0)
        self.assertEqual(low["tier"], "720p")
        self.assertFalse(low["realtime"])

    def test_probe_command_is_bounded_and_synthetic(self):
        command = benchmark.probe_command(seconds=3, height=720)
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("testsrc=size=1280x720:rate=30", command)
        self.assertEqual(command[command.index("-t") + 1], "3")
        self.assertEqual(command[-1], "-")

    def test_run_probe_returns_none_on_failure(self):
        with mock.patch.object(benchmark.subprocess, "run", side_effect=OSError("no ffmpeg")):
            self.assertIsNone(benchmark.run_probe())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg needed for a real probe")
    def test_real_probe_measures_a_positive_rate(self):
        fps = benchmark.run_probe(seconds=2, height=480)
        self.assertIsNotNone(fps)
        self.assertGreater(fps, 0.0)


if __name__ == "__main__":
    unittest.main()
