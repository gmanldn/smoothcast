"""Receiver-safe HLS frame-rate policy; no ffmpeg or real Cast process (#545)."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import streamer  # noqa: E402


class TranscodeFrameRateTests(unittest.TestCase):
    def setUp(self):
        self.session = streamer.Session()

    def filters(self, *, fps=60.0, speed=1.0, bitmap=False,
                size=(1920, 1080), software=True):
        return self.session._filter_args(
            False, None, software, speed, embedded_bitmap=bitmap,
            embedded_subtitle_index=0 if bitmap else None,
            source_fps=fps, video_size=size,
        )

    def test_1080p60_software_output_is_explicitly_limited_to_30(self):
        args = self.filters()
        self.assertEqual(args, ["-vf", "fps=fps=30"])
        self.assertIn("4.1", self.session._codec_args("balanced", True))

    def test_4k60_downscales_and_caps_frame_rate(self):
        args = self.filters(size=(3840, 2160))
        self.assertEqual(args[0], "-vf")
        self.assertIn("fps=fps=30", args[1])
        self.assertIn("scale=w=1920:h=1080", args[1])
        self.assertLess(args[1].index("fps=fps=30"), args[1].index("scale="))

    def test_bitmap_subtitle_overlay_caps_final_output_without_discarding_overlay(self):
        args = self.filters(bitmap=True, size=(3840, 2160))
        self.assertEqual(args[0], "-filter_complex")
        self.assertIn("[0:s:0]setpts=", args[1])
        self.assertIn("overlay=eof_action=pass:repeatlast=0", args[1])
        self.assertIn("fps=fps=30", args[1])
        self.assertIn("scale=w=1920:h=1080", args[1])
        self.assertLess(args[1].index("overlay="), args[1].index("fps=fps=30"))

    def test_playback_rate_is_included_in_effective_output_fps(self):
        args = self.filters(fps=25, speed=2)
        self.assertEqual(args, ["-vf", "setpts=PTS/2,fps=fps=30"])
        bitmap = self.filters(fps=25, speed=2, bitmap=True)
        self.assertIn("setpts=PTS/2,fps=fps=30", bitmap[1])

    def test_normal_film_cadences_are_not_duplicated_or_filtered(self):
        for fps in (23.976, 24, 25, 29.97, 30):
            with self.subTest(fps=fps):
                self.assertEqual(self.filters(fps=fps), [])
        self.assertEqual(self.filters(fps=60, speed=0.5), ["-vf", "setpts=PTS/0.5"])

    def test_nonfinite_or_unknown_probe_rate_never_breaks_filtergraph(self):
        for fps in (0, float("nan"), float("inf")):
            with self.subTest(fps=fps):
                self.assertNotIn("fps=", " ".join(self.filters(fps=fps)))

    def test_hardware_path_also_constrains_framerate(self):
        # Avoid forcing hardware frame uploads purely for a timestamp filter.
        self.assertEqual(self.filters(software=False), ["-vf", "fps=fps=30"])


if __name__ == "__main__":
    unittest.main()
