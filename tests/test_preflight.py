"""P2 #47: private MKV encoder preflight, errors and Cast ordering."""
from __future__ import annotations

import ast
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import preflight
import streamer


class PreflightTests(unittest.TestCase):
    def media(self, root: Path) -> streamer.MediaInfo:
        path = root / "Movie.mkv"
        path.write_bytes(b"movie fixture")
        return streamer.MediaInfo(
            path=path, audio_tracks=1,
            audio_streams=[streamer.AudioTrack(0, "aac", 2, "eng")],
            subtitle_tracks=[streamer.SubtitleTrack(0, "subrip", "eng")],
        )

    def test_short_private_render_uses_selected_audio_and_deletes_temp_media(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            subtitles = Path(folder) / "Film.srt"
            subtitles.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nCaption\n", encoding="utf-16",
            )
            seen = {}
            def complete(args, **_kwargs):
                if args[0] == "ffprobe":
                    return subprocess.CompletedProcess(
                        args, 0, '{"streams":[{"nb_read_frames":"12"}]}', "",
                    )
                seen["args"] = args
                output = Path(args[-1])
                self.assertTrue(output.parent.name.startswith("smoothcast-preflight-"))
                self.assertEqual((output.parent / "preflight-subs.srt").read_text("utf-8"),
                                 "1\n00:00:00,000 --> 00:00:01,000\nCaption\n")
                output.write_bytes(b"matroska sample")
                seen["folder"] = output.parent
                return subprocess.CompletedProcess(args, 0, "", "")
            with mock.patch.object(preflight.subprocess, "run", side_effect=complete):
                report = preflight.check_media(
                    media, audio_track_index=0,
                    subs_file=subtitles, burn_subs=True,
                )
            self.assertGreater(report.bytes_rendered, 0)
            args = seen["args"]
            self.assertIn("0:a:0", args)
            self.assertIn("-t", args)
            self.assertIn("-vf", args)
            self.assertIn("preflight-subs.srt", " ".join(args))
            self.assertNotIn("catt", " ".join(args))
            self.assertFalse(seen["folder"].exists())

    def test_failure_and_timeout_report_clearly(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            with mock.patch.object(
                preflight.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 1, "", "Unknown decoder"),
            ):
                with self.assertRaisesRegex(preflight.PreflightError, "Unknown decoder"):
                    preflight.check_media(media)
            with mock.patch.object(
                preflight.subprocess, "run",
                side_effect=subprocess.TimeoutExpired(["ffmpeg"], 2),
            ):
                with self.assertRaisesRegex(preflight.PreflightError, "timed out"):
                    preflight.check_media(media, timeout=2)

    def test_empty_success_is_not_misreported(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            with mock.patch.object(
                preflight.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ):
                with self.assertRaisesRegex(preflight.PreflightError, "no media"):
                    preflight.check_media(media)

    def test_container_without_decoded_video_frames_is_rejected(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            def empty_frames(args, **_kwargs):
                if args[0] == "ffprobe":
                    return subprocess.CompletedProcess(
                        args, 0, '{"streams":[{"nb_read_frames":"0"}]}', "",
                    )
                Path(args[-1]).write_bytes(b"container header only")
                return subprocess.CompletedProcess(args, 0, "", "")
            with mock.patch.object(preflight.subprocess, "run", side_effect=empty_frames):
                with self.assertRaisesRegex(preflight.PreflightError, "no video frames"):
                    preflight.check_media(media)

    def test_missing_selected_stream_and_bitmap_subtitle_fail_before_ffmpeg(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            with mock.patch.object(preflight.subprocess, "run") as run:
                with self.assertRaisesRegex(preflight.PreflightError, "audio track"):
                    preflight.check_media(media, audio_track_index=9)
                with self.assertRaisesRegex(preflight.PreflightError, "bitmap-only"):
                    preflight.check_media(media, embedded_subtitle_index=99)
            run.assert_not_called()

    def test_invalid_caption_fails_before_ffmpeg(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            bad = Path(folder) / "bad.srt"
            bad.write_bytes(b"not a subtitle file")
            with mock.patch.object(preflight.subprocess, "run") as run:
                with self.assertRaisesRegex(preflight.PreflightError, "timestamp"):
                    preflight.check_media(media, subs_file=bad)
            run.assert_not_called()

    def test_fingerprint_changes_when_file_or_caption_changes(self):
        with TemporaryDirectory() as folder:
            media = self.media(Path(folder))
            subs = Path(folder) / "sub.srt"
            subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
            params = dict(audio_track_index=0, subs_file=subs,
                          burn_subs=False, embedded_subtitle_index=None)
            first = preflight.fingerprint(media.path, **params)
            self.assertEqual(first, preflight.fingerprint(media.path, **params))
            subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nDifferent\n")
            self.assertNotEqual(first, preflight.fingerprint(media.path, **params))
            self.assertNotEqual(first, preflight.fingerprint(
                media.path, **{**params, "audio_track_index": 1}
            ))

    def test_gui_preflight_precedes_any_previous_tv_stop(self):
        source = (ROOT / "src" / "cast_control.py").read_text("utf-8")
        window = next(
            x for x in ast.parse(source).body
            if isinstance(x, ast.ClassDef) and x.name == "MainWindow"
        )
        method = next(x for x in window.body
                      if isinstance(x, ast.FunctionDef) and x.name == "_cast_path")
        body = ast.get_source_segment(source, method)
        work = body.split("def work():", 1)[1].split("def done(", 1)[0]
        self.assertIn('path.suffix.lower() == ".mkv"', work)
        self.assertIn("preflight.fingerprint(", work)
        self.assertLess(work.index("preflight.check_media("),
                        work.index("previous.stop(device, send_stop="))
        self.assertIn("self._preflight_ok.add(fingerprint)", work)
        self.assertIn("if previous is not None and previous is self.session", body)

    def test_real_local_ffmpeg_renders_mkv_when_encoders_installed(self):
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None or shutil.which("ffprobe") is None:
            self.skipTest("FFmpeg/FFprobe are unavailable")
        listing = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        if any(codec not in listing.stdout for codec in ("libx264", "mpeg4", "aac")):
            self.skipTest("Required FFmpeg encoders are unavailable")
        with TemporaryDirectory() as folder:
            root = Path(folder)
            movie = root / "sample.mkv"
            make = subprocess.run(
                [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
                 "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=15:d=1",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                 "-c:v", "mpeg4", "-c:a", "aac",
                 "-shortest", "-y", str(movie)],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(make.returncode, 0, make.stderr[:500])
            media = streamer.MediaInfo(path=movie)
            result = preflight.check_media(media, timeout=20)
            self.assertGreater(result.bytes_rendered, 0)
            self.assertEqual([p.name for p in root.iterdir()], ["sample.mkv"])


if __name__ == "__main__":
    unittest.main()
