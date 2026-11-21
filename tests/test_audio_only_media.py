"""Audio-only queue probe, preflight and HLS encoder regressions."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import preflight
import streamer


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class AudioOnlyMediaTests(unittest.TestCase):
    def make_fixture(self, path: Path, codec: str) -> None:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=2.2", "-vn", "-c:a", codec,
             "-y", str(path)], check=True, capture_output=True, timeout=20,
        )

    def test_mp3_flac_and_aac_are_probeable_as_audio_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixtures = (("track.mp3", "libmp3lame", "mp3"),
                        ("track.flac", "flac", "flac"),
                        ("track.m4a", "aac", "aac"))
            for name, encoder, expected_codec in fixtures:
                with self.subTest(name=name):
                    path = root / name
                    self.make_fixture(path, encoder)
                    media = streamer.ffprobe(path)
                    self.assertTrue(media.is_audio_only)
                    self.assertFalse(media.has_video)
                    self.assertEqual(media.vcodec, "")
                    self.assertEqual(media.audio_streams[0].codec, expected_codec)
                    self.assertGreater(media.duration, 2.0)
                    self.assertFalse(media.direct_ok)
                    self.assertIn("AAC transcode", media.direct_reason)

    def test_audio_preflight_decodes_selected_track_without_video(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "track.flac"
            self.make_fixture(path, "flac")
            media = streamer.ffprobe(path)
            result = preflight.check_media(media)
            self.assertGreater(result.bytes_rendered, 0)
            self.assertEqual(result.sample_seconds, 0.8)

    def test_audio_hls_plan_maps_audio_and_never_constructs_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "track.flac"
            self.make_fixture(path, "flac")
            media = streamer.ffprobe(path)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.pid = 12345
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
                 mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
                 mock.patch.object(streamer.video_policy, "make_plan") as video_plan, \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 0, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None,
                    burn_subs=False, title="Track",
                )
            args = popen.call_args_list[0].args[0]
            self.assertIn("-vn", args)
            self.assertEqual(args[args.index("-map") + 1], "0:a:0")
            self.assertEqual(args[args.index("-c:a") + 1], "aac")
            self.assertFalse(any(value == "-c:v" or value.startswith("-vf") for value in args))
            self.assertFalse(any(value.startswith("0:v") for value in args))
            video_plan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
