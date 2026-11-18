"""GTK-free compatibility contracts: MKV, external subtitles, Cast targets."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer
import castctl


class MediaCompatibilityTests(unittest.TestCase):
    def test_mkv_subtitles_audio_formats_and_framerate_enumerated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Film.mkv"
            path.touch()
            payload = {
                "format": {"duration": "123.5", "bit_rate": "5100000"},
                "streams": [
                    {"codec_type": "video", "codec_name": "hevc",
                     "width": 3840, "height": 2160, "pix_fmt": "yuv420p10le",
                     "avg_frame_rate": "60000/1001"},
                    {"codec_type": "audio", "codec_name": "eac3", "channels": 6},
                    {"codec_type": "audio", "codec_name": "aac", "channels": 2},
                    {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
                     "tags": {"language": "eng"}},
                    {"codec_type": "subtitle", "codec_name": "subrip",
                     "tags": {"language": "eng", "title": "English"},
                     "disposition": {"default": 1}},
                    {"codec_type": "subtitle", "codec_name": "ass",
                     "tags": {"language": "fra"}},
                ],
            }
            result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
            with mock.patch.object(streamer.subprocess, "run", return_value=result):
                media = streamer.ffprobe(path)
        self.assertAlmostEqual(media.duration, 123.5)
        self.assertAlmostEqual(media.fps, 59.94, places=1)
        self.assertEqual(media.acodec, "eac3")
        self.assertEqual(media.audio_tracks, 2)
        self.assertEqual([t.codec for t in media.subtitle_tracks],
                         ["hdmv_pgs_subtitle", "subrip", "ass"])
        self.assertFalse(media.direct_ok)
        selected = streamer.preferred_embedded_subtitle(media)
        self.assertEqual(selected.index, 1)
        self.assertTrue(selected.is_text)
        self.assertEqual(streamer.preferred_embedded_subtitle(media, 2).codec, "ass")
        self.assertIsNone(streamer.preferred_embedded_subtitle(media, 0))

    def test_bitmap_only_mkv_cannot_be_misrepresented_as_text(self):
        media = streamer.MediaInfo(
            path=Path("film.mkv"),
            subtitle_tracks=[streamer.SubtitleTrack(0, "hdmv_pgs_subtitle", "eng")],
        )
        self.assertIsNone(streamer.preferred_embedded_subtitle(media))
        self.assertIn("unsupported", media.subtitle_tracks[0].label)

    def test_subtitle_filter_uses_embedded_stream_index(self):
        session = streamer.Session()
        source = Path("/tmp/movie name.mkv")
        args = session._filter_args(
            False, None, True, 1.0,
            embedded_subtitle_index=2, embedded_source=source,
        )
        self.assertEqual(args, ["-vf", "subtitles=filename=/tmp/movie name.mkv:si=2"])
        hw = session._filter_args(
            False, None, False, 1.0,
            embedded_subtitle_index=0, embedded_source=source,
        )
        self.assertIn("hwdownload,format=nv12", hw[1])
        self.assertIn("hwupload", hw[1])

    def test_filter_filename_escapes_critical_metacharacters(self):
        path = Path("/tmp/film's:demo,[01].mkv")
        value = streamer.Session._filter_path(path)
        self.assertIn(r"\\:", value)
        self.assertIn(r"\,", value)
        self.assertIn(r"\[", value)
        self.assertIn(r"\]", value)
        self.assertIn("\\\\\\'", value)

    def test_software_encoder_restricts_bit_depth_and_resolution(self):
        session = streamer.Session()
        command = session._codec_args("balanced", software=True)
        self.assertIn("yuv420p", command)
        self.assertIn("4.1", command)
        filter_args = session._filter_args(
            False, None, True, 1.0, video_size=(3840, 2160),
        )
        self.assertIn("scale=w=1920:h=1080:force_original_aspect_ratio=decrease",
                      filter_args[1])

    def test_external_subtitles_match_only_related_video(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            video = home / "Film.mkv"
            video.touch()
            (home / "Film2.srt").write_text("wrong")
            (home / "Film.en.ass").write_text("styled")
            (home / "Film.eng.srt").write_text("english")
            (home / "Other.srt").write_text("wrong")
            self.assertEqual(streamer.find_subtitles(video).name, "Film.eng.srt")
            (home / "Film.srt").write_text("exact")
            self.assertEqual(streamer.find_subtitles(video).name, "Film.srt")
        self.assertTrue({".srt", ".ass", ".ssa"}.issubset(streamer.SUBTITLE_EXTS))
        self.assertNotIn(".ass", streamer.CAST_SUBTITLE_EXTS)


class ReceiverTests(unittest.TestCase):
    def test_manual_receiver_ip_must_be_private_unicast(self):
        self.assertEqual(castctl.validate_manual_target(" 192.168.0.25 "),
                         "192.168.0.25")
        self.assertEqual(castctl.validate_manual_target("10.0.0.99"), "10.0.0.99")
        for invalid in ("google-tv.local", "127.0.0.1", "0.0.0.0", "224.0.0.1",
                        "8.8.8.8", "169.254.3.4", "::1"):
            with self.subTest(address=invalid), self.assertRaises(ValueError):
                castctl.validate_manual_target(invalid)

    def test_malformed_port_does_not_discard_other_cast_devices(self):
        data = {
            "Google TV": {"host": "192.168.1.25", "port": "not-a-port",
                          "model_name": "Google TV"},
            "Nest Hub": {"host": "192.168.1.26", "port": 8009,
                         "model_name": "Nest Hub"},
        }
        result = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with mock.patch.object(castctl, "_run", return_value=result):
            devices = castctl.scan()
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].port, 0)
        self.assertEqual(devices[1].port, 8009)


if __name__ == "__main__":
    unittest.main()
