"""Geometry regressions for rotation, 1080p bounds and even H.264 frames.

FFmpeg probes are local, headless and produce one short disposable frame.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer


class RotationGeometryTests(unittest.TestCase):
    def filter(self, width, height, rotation=0, software=True):
        return streamer.Session()._filter_args(
            False, None, software, 1.0, rotation, video_size=(width, height),
        )

    def test_rotated_source_is_bounded_by_output_not_input_orientation(self):
        self.assertEqual(
            self.filter(1920, 1080, rotation=90),
            ["-vf", "transpose=1,scale=w=1920:h=1080:"
             "force_original_aspect_ratio=decrease:force_divisible_by=2"],
        )
        self.assertEqual(
            self.filter(1080, 1920, rotation=90),
            ["-vf", "transpose=1"],
        )
        self.assertEqual(streamer._rotated_dimensions(1920, 1080, 270), (1080, 1920))
        self.assertEqual(streamer._rotated_dimensions(1920, 1080, 180), (1920, 1080))

    def test_odd_pictures_are_rounded_to_even_dimensions(self):
        self.assertEqual(
            self.filter(641, 359),
            ["-vf", "scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2"],
        )
        self.assertEqual(
            self.filter(641, 359, rotation=90),
            ["-vf", "transpose=1,scale=w=trunc(iw/2)*2:"
             "h=trunc(ih/2)*2"],
        )
        self.assertEqual(
            self.filter(2560, 720, rotation=90, software=False),
            ["-vf", "hwdownload,format=nv12,transpose=1,"
             "scale=w=1920:h=1080:force_original_aspect_ratio=decrease:"
             "force_divisible_by=2,hwupload"],
        )


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg/FFprobe needed for actual pixel geometry checks")
class RealEncodedGeometryTests(unittest.TestCase):
    def test_ffmpeg_outputs_even_1080p_bounded_picture_with_correct_aspect(self):
        cases = (
            # Source is 1080p, but its *rotated* height requires scaling.
            (1920, 1080, 90),
            # Both dimensions are odd, so even pixel format needs rounding.
            (641, 359, 0),
            # Very wide source rotated into a tall picture.
            (2560, 720, 90),
        )
        with tempfile.TemporaryDirectory() as folder:
            for index, (width, height, rotation) in enumerate(cases):
                with self.subTest(source=(width, height), rotation=rotation):
                    vf = streamer.Session()._filter_args(
                        False, None, True, 1.0, rotation,
                        video_size=(width, height),
                    )
                    self.assertEqual(vf[0], "-vf")
                    output = Path(folder) / f"geometry-{index}.mkv"
                    command = [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i",
                        f"testsrc=size={width}x{height}:rate=1:duration=1",
                        *vf, "-frames:v", "1", "-pix_fmt", "yuv420p",
                        "-c:v", "mpeg4", "-q:v", "4", str(output),
                    ]
                    subprocess.run(command, capture_output=True, check=True, timeout=30)
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "json",
                         str(output)],
                        capture_output=True, text=True, check=True, timeout=10,
                    )
                    stream = json.loads(probe.stdout)["streams"][0]
                    out_w, out_h = stream["width"], stream["height"]
                    self.assertEqual(out_w % 2, 0)
                    self.assertEqual(out_h % 2, 0)
                    self.assertLessEqual(out_w, 1920)
                    self.assertLessEqual(out_h, 1080)
                    natural_w, natural_h = streamer._rotated_dimensions(
                        width, height, rotation,
                    )
                    self.assertLess(
                        abs(out_w / out_h - natural_w / natural_h), 0.01,
                        "Picture aspect changed by more than normal even rounding",
                    )


if __name__ == "__main__":
    unittest.main()
