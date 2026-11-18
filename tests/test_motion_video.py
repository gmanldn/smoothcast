"""Motion-video selection when a container lists attached cover artwork first.

All playback-process checks are headless; optional FFmpeg fixture verifies a
real MKV where one-frame JPEG is stream 0 without the attached_pic flag.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer
import screenshot
import dlna
from gui_source import main_window_methods


class StreamSelectionTests(unittest.TestCase):
    def probe(self, streams):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "film.mkv"
            path.write_bytes(b"probe fixture")
            result = subprocess.CompletedProcess(
                [], 0, json.dumps({"format": {"duration": "12"},
                                   "streams": streams}), "",
            )
            with mock.patch.object(streamer.subprocess, "run", return_value=result):
                return streamer.ffprobe(path)

    def test_attached_cover_before_motion_video_is_skipped(self):
        media = self.probe([
            {"index": 0, "codec_type": "video", "codec_name": "mjpeg",
             "width": 900, "height": 900, "disposition": {"attached_pic": 1}},
            {"index": 1, "codec_type": "video", "codec_name": "h264",
             "width": 1920, "height": 1080, "avg_frame_rate": "24000/1001",
             "disposition": {"default": 1}},
            {"index": 2, "codec_type": "audio", "codec_name": "aac"},
        ])
        self.assertEqual(media.video_stream_index, 1)
        self.assertEqual(media.vcodec, "h264")
        self.assertEqual(media.resolution, "1920x1080")
        self.assertAlmostEqual(media.fps, 23.976, places=2)

    def test_mkv_unflagged_one_frame_jpeg_is_not_mistaken_for_film(self):
        media = self.probe([
            {"index": 0, "codec_type": "video", "codec_name": "mjpeg",
             "tags": {"DURATION": "00:00:00.040"}, "width": 40, "height": 40},
            {"index": 1, "codec_type": "video", "codec_name": "mpeg4",
             "tags": {"DURATION": "00:00:12"}, "disposition": {"default": 1},
             "width": 640, "height": 360, "avg_frame_rate": "25/1"},
        ])
        self.assertEqual(media.video_stream_index, 1)
        self.assertEqual(media.resolution, "640x360")

    def test_artwork_only_is_not_accepted_as_movie(self):
        with self.assertRaisesRegex(streamer.StreamError, "No motion-video"):
            self.probe([
                {"index": 0, "codec_type": "video", "codec_name": "png",
                 "disposition": {"attached_pic": 1}},
            ])
        with self.assertRaisesRegex(streamer.StreamError, "No motion-video"):
            self.probe([
                {"index": 0, "codec_type": "video", "codec_name": "mjpeg",
                 "tags": {"DURATION": "00:00:00.04"}},
            ])

    def test_single_mjpeg_motion_video_is_still_supported(self):
        media = self.probe([
            {"index": 0, "codec_type": "video", "codec_name": "mjpeg",
             "tags": {"DURATION": "00:00:12"}, "avg_frame_rate": "25/1"},
        ])
        self.assertEqual(media.vcodec, "mjpeg")
        self.assertEqual(media.video_stream_index, 0)

    def test_transcode_uses_selected_absolute_video_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            movie = root / "movie.mkv"
            movie.write_bytes(b"test")
            media = streamer.MediaInfo(
                path=movie, duration=2, vcodec="h264",
                width=160, height=90, pix_fmt="yuv420p",
                video_stream_index=2,
            )
            session = streamer.Session()
            process = mock.MagicMock()
            process.poll.return_value = 0
            process.pid = 123
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.10"), \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=process) as start, \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer, "_save_session"):
                session.start_transcode(
                    media, 0, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None, burn_subs=False,
                    title="Movie",
                )
            command = start.call_args_list[0].args[0]
            self.assertEqual(command[command.index("-map") + 1], "0:2")

    def test_dlna_preparation_maps_selected_absolute_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            movie = root / "movie.mkv"
            movie.write_bytes(b"test")
            output = root / "prepared.mp4"
            media = streamer.MediaInfo(
                path=movie, duration=2, vcodec="h264", pix_fmt="yuv420p",
                width=160, height=90, fps=24, video_stream_index=1,
            )
            def complete(args, **kwargs):
                Path(args[-1]).write_bytes(b"prepared mp4")
                proc = mock.MagicMock()
                proc.poll.return_value = 0
                proc.returncode = 0
                return proc
            with mock.patch.object(dlna.subprocess, "Popen", side_effect=complete) as start:
                dlna.prepare_mp4(media, output)
            command = start.call_args.args[0]
            self.assertEqual(command[command.index("-map") + 1], "0:1")

    def test_selected_absolute_index_is_used_in_cast_and_dlna(self):
        from types import SimpleNamespace
        import inspect
        body = inspect.getsource(streamer.Session.start_transcode)
        self.assertIn('f"0:{media.video_stream_index}"', body)
        body = inspect.getsource(dlna.prepare_mp4)
        self.assertIn('f"0:{media.video_stream_index}"', body)
        methods = main_window_methods()
        self.assertIn("video_stream_index=video_index", methods["_start_preview"])
        self.assertIn("video_stream_index=video_index", methods["_screenshot"])


class CaptureMappingTests(unittest.TestCase):
    def test_screenshot_maps_motion_video_absolute_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            src = root / "movie.mkv"
            src.write_bytes(b"mock")
            def create(args, **kwargs):
                Path(args[-1]).write_bytes(b"PNG")
                return subprocess.CompletedProcess(args, 0, "", "")
            with mock.patch.object(screenshot.subprocess, "run", side_effect=create) as ff:
                screenshot.capture_frame(src, 1.0, root / "frames", video_stream_index=2)
            args = ff.call_args.args[0]
            self.assertEqual(args[args.index("-map") + 1], "0:2")

    def test_preview_maps_motion_video_absolute_stream(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "movie.mkv"
            src.write_bytes(b"mock")
            completed = subprocess.CompletedProcess([], 0, b"\xff\xd8sample", b"")
            with mock.patch.object(screenshot.subprocess, "run", return_value=completed) as ff:
                screenshot.preview_frame(src, 1.0, video_stream_index=1)
            args = ff.call_args.args[0]
            self.assertEqual(args[args.index("-map") + 1], "0:1")

    def test_invalid_stream_rejected_without_spawning_decoder(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / "movie.mkv"
            src.touch()
            with mock.patch.object(screenshot.subprocess, "run") as ff:
                with self.assertRaisesRegex(screenshot.CaptureError, "stream index"):
                    screenshot.preview_frame(src, 0, video_stream_index=-1)
                with self.assertRaisesRegex(screenshot.CaptureError, "stream index"):
                    screenshot.capture_frame(src, 0, Path(folder), video_stream_index=True)
                ff.assert_not_called()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Actual FFmpeg/FFprobe required for movie-cover fixture")
class RealMkvArtworkTests(unittest.TestCase):
    def test_real_unflagged_mkv_cover_before_motion_video(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cover = root / "cover.jpg"
            movie = root / "film.mkv"
            img = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:size=48x48:duration=1",
                "-frames:v", "1", str(cover),
            ]
            subprocess.run(img, capture_output=True, check=True, timeout=20)
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(cover),
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5:duration=2",
                "-map", "0:v:0", "-map", "1:v:0",
                "-c:v:0", "mjpeg", "-disposition:v:0", "attached_pic",
                "-c:v:1", "mpeg4", "-q:v:1", "4",
                "-disposition:v:1", "default", str(movie),
            ]
            subprocess.run(command, capture_output=True, check=True, timeout=30)
            media = streamer.ffprobe(movie)
            self.assertEqual(media.video_stream_index, 1)
            self.assertEqual(media.resolution, "160x90")
            jpeg = screenshot.preview_frame(movie, 1.0,
                                            video_stream_index=media.video_stream_index)
            self.assertTrue(jpeg.startswith(b"\xff\xd8"))
            shot = screenshot.capture_frame(movie, 1.0, root / "captures",
                                            video_stream_index=media.video_stream_index)
            self.assertGreater(shot.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
