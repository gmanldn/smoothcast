"""Headless playback-corpus shape checks: no ffmpeg, GTK, network or device."""
from __future__ import annotations

from pathlib import Path
from runpy import run_path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import media_matrix  # noqa: E402
import streamer  # noqa: E402
# Load the dependency-free capability table directly: importing the
# fakecast package initialises its PyChromecast protocol server, which is
# intentionally absent from the fast syntax lane.
_fake_profiles = run_path(str(ROOT / "fakecast" / "profiles.py"))
PROFILES = _fake_profiles["PROFILES"]
supports = _fake_profiles["supports"]


class SourceShapeTests(unittest.TestCase):
    def test_unique_48_cases_cover_containers_codecs_and_subtitles(self):
        cases = media_matrix.SHAPES
        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case.name for case in cases}), 48)
        self.assertEqual({c.extension for c in cases},
                         {"mp4", "mkv", "webm", "avi", "ts", "mov"})
        self.assertGreaterEqual(
            {c.video for c in cases},
            {"h264", "hevc", "vp9", "av1", "mpeg2video", "mpeg4"},
        )
        self.assertGreaterEqual(
            {c.audio for c in cases},
            {"aac", "ac3", "eac3", "dts", "flac", "opus", "mp3"},
        )
        self.assertGreaterEqual(
            {c.subtitles for c in cases},
            {"none", "subrip", "ass", "hdmv_pgs_subtitle", "mov_text"},
        )

    def test_each_source_is_parseable_by_the_real_ffprobe_metadata_parser(self):
        for shape in media_matrix.SHAPES:
            with self.subTest(shape=shape.name):
                media = streamer.MediaInfo(
                    path=Path(f"/synthetic/{shape.name}.{shape.extension}"),
                )
                streamer._read_probe(media, shape.probe())
                self.assertEqual(media.vcodec, shape.video)
                self.assertEqual(media.acodec, shape.audio)
                self.assertEqual((media.width, media.height),
                                 (shape.width, shape.height))
                self.assertEqual(media.fps, shape.fps)
                self.assertEqual(media.audio_tracks, 1)
                self.assertEqual(media.duration, 120)
                self.assertEqual(len(media.subtitle_tracks),
                                 int(shape.subtitles != "none"))
                if shape.subtitles != "none":
                    self.assertEqual(media.subtitle_tracks[0].codec,
                                     shape.subtitles)
                self.assertIs(type(media.direct_ok), bool)
                self.assertTrue(media.direct_reason)

    def test_fake_receiver_rejects_malformed_video_codec_levels(self):
        stream = {
            "codec": "h264", "profile": "high", "level": "4.1",
            "width": 1920, "height": 1080, "fps": 30,
        }
        self.assertTrue(supports("chromecast-gen2", stream))
        for level in (
            "-1.0", "4.-1", "4.10", "4", "bogus", None,
            " 4.1", "4.1 ", "+4.1", "4.+1", "04.1", "0.0",
            "4.01", "4.1\n", "999.1", float("inf"),
        ):
            with self.subTest(level=level):
                self.assertFalse(supports(
                    "chromecast-gen2", {**stream, "level": level},
                ))
        self.assertEqual(_fake_profiles["level_tuple"]("5.2"), (5, 2))

    def test_fake_receiver_rejects_noninteger_video_geometry(self):
        # A Python bool is an int subclass; ffprobe dimensions/fps are not.
        valid = {
            "codec": "h264", "profile": "high", "level": "4.1",
            "width": 1920, "height": 1080, "fps": 30,
        }
        self.assertTrue(supports("chromecast-gen2", valid))
        for field in ("width", "height", "fps"):
            for bad in (True, False, 0, -1, 1.5, "1", None):
                with self.subTest(field=field, bad=bad):
                    self.assertFalse(supports(
                        "chromecast-gen2", {**valid, field: bad},
                    ))
        # The deliberately unconstrained generic test profile is unchanged.
        self.assertTrue(supports("generic", {"codec": "unrecognised"}))

    def test_every_fake_receiver_profile_rejects_undocumented_video_codecs(self):
        """480-ish checks exercise fake capability, not end-to-end planner."""
        self.assertGreaterEqual(len(PROFILES), 6)
        for shape in media_matrix.SHAPES:
            video_codec = {"hevc": "h265", "mpeg2video": "mpeg2"}.get(
                shape.video, shape.video,
            )
            video_profile = {
                "h264": "high",
                "h265": "main10" if shape.pix_fmt == "yuv420p10le" else "main",
                "vp9": "2" if shape.pix_fmt == "yuv420p10le" else "0",
                "av1": "main",
            }.get(video_codec, "")
            stream = {
                "codec": video_codec,
                "profile": video_profile,
                "level": "5.1" if shape.width > 1920 else "4.1",
                "width": shape.width,
                "height": shape.height,
                "fps": shape.fps,
            }
            for profile, spec in PROFILES.items():
                with self.subTest(shape=shape.name, profile=profile):
                    accepted = supports(profile, stream)
                    self.assertIs(type(accepted), bool)
                    if profile != "generic" and video_codec not in {
                        limit.codec for limit in spec.codecs
                    }:
                        self.assertFalse(accepted)


    def test_report_matches_synthetic_video_capability_matrix(self):
        generator = run_path(str(ROOT / "scripts" / "ci" / "render_playback_matrix.py"))
        expected = generator["render"]()
        actual = (ROOT / "docs" / "PLAYBACK_MATRIX.md").read_text("utf-8")
        self.assertEqual(actual, expected, "Regenerate the checked-in matrix using --write")
        self.assertEqual(sum(line.startswith("| sample-") for line in actual.splitlines()), 48)
        self.assertIn("Not a direct/remux/transcode/playability matrix", actual)
        self.assertIn("not playable-or-typed-refusal evidence", actual)


if __name__ == "__main__":
    unittest.main()
