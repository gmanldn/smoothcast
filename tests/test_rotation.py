"""Regression checks for video rotation in the HLS transcode chain."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer


class RotationTests(unittest.TestCase):
    def test_normalize_rotation(self):
        self.assertEqual(streamer.normalize_rotation(0), 0)
        self.assertEqual(streamer.normalize_rotation(90), 90)
        self.assertEqual(streamer.normalize_rotation(180), 180)
        self.assertEqual(streamer.normalize_rotation(270), 270)
        # Anything else falls back to no rotation.
        self.assertEqual(streamer.normalize_rotation(45), 0)
        self.assertEqual(streamer.normalize_rotation(360), 0)
        self.assertEqual(streamer.normalize_rotation("90"), 90)
        self.assertEqual(streamer.normalize_rotation(None), 0)

    def test_rotation_filters(self):
        self.assertEqual(streamer.rotation_filters(0), [])
        self.assertEqual(streamer.rotation_filters(90), ["transpose=1"])
        self.assertEqual(streamer.rotation_filters(180), ["transpose=2,transpose=2"])
        self.assertEqual(streamer.rotation_filters(270), ["transpose=2"])

    def _filter_args(self, **kwargs):
        defaults = dict(burn_subs=False, staged=None, software=True, speed=1.0, rotation=0)
        defaults.update(kwargs)
        return streamer.Session()._filter_args(**defaults)

    def test_no_rotation_emits_no_filter(self):
        self.assertEqual(self._filter_args(), [])
        self.assertEqual(self._filter_args(rotation=0), [])

    def test_rotation_in_software_chain(self):
        self.assertEqual(self._filter_args(rotation=90), ["-vf", "transpose=1"])
        self.assertEqual(self._filter_args(rotation=180), ["-vf", "transpose=2,transpose=2"])
        self.assertEqual(self._filter_args(rotation=270), ["-vf", "transpose=2"])

    def test_rotation_round_trips_vaapi_through_software(self):
        # Pure VAAPI (no subtitles) must download/upload so the software
        # transpose can run on CPU frames.
        self.assertEqual(
            self._filter_args(software=False, rotation=90),
            ["-vf", "hwdownload,format=nv12,transpose=1,hwupload"],
        )
        self.assertEqual(
            self._filter_args(software=False, rotation=270),
            ["-vf", "hwdownload,format=nv12,transpose=2,hwupload"],
        )

    def test_rotation_with_subtitles_and_speed(self):
        staged = Path("burned_subs.srt")
        # Software: plain -vf chain even with subtitles.
        self.assertEqual(
            self._filter_args(burn_subs=True, staged=staged, rotation=90, speed=1.5),
            ["-vf", "subtitles=filename=burned_subs.srt,setpts=PTS/1.5,transpose=1"],
        )
        self.assertEqual(
            self._filter_args(burn_subs=True, staged=staged, software=True, rotation=180, speed=0.5),
            ["-vf", "subtitles=filename=burned_subs.srt,setpts=PTS/0.5,transpose=2,transpose=2"],
        )
        # Pure VAAPI + subtitles already forces the software round trip.
        self.assertEqual(
            self._filter_args(software=False, burn_subs=True, staged=staged, rotation=90),
            ["-vf", "hwdownload,format=nv12,subtitles=filename=burned_subs.srt,transpose=1,hwupload"],
        )


if __name__ == "__main__":
    unittest.main()
