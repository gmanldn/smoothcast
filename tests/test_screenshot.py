"""Screenshot capture safety and non-overwrite regression tests."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import screenshot


class ScreenshotTests(unittest.TestCase):
    def test_preview_frame_is_bounded_and_stays_in_memory(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "video.mkv"
            source.touch()
            jpeg = bytes.fromhex("ffd8ffe0") + b"sample"
            result = subprocess.CompletedProcess([], 0, jpeg, b"")
            with mock.patch.object(screenshot.subprocess, "run", return_value=result) as run:
                self.assertEqual(screenshot.preview_frame(source, 62.5), jpeg)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("-ss") + 1], "62.5")
            self.assertIn("scale=640:360:force_original_aspect_ratio=decrease", args)
            self.assertIn("pipe:1", args)
            self.assertEqual(run.call_args.kwargs["timeout"], 12)
            self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_preview_does_not_spawn_ffmpeg_for_missing_or_invalid_input(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "video.mkv"
            with mock.patch.object(screenshot.subprocess, "run") as run:
                with self.assertRaises(screenshot.CaptureError):
                    screenshot.preview_frame(source, 3)
                source.touch()
                with self.assertRaisesRegex(screenshot.CaptureError, "Invalid preview"):
                    screenshot.preview_frame(source, float("nan"))
                run.assert_not_called()

    def test_preview_rejects_empty_frames_and_times_out(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "video.mkv"
            source.touch()
            with mock.patch.object(screenshot.subprocess, "run", return_value=
                                   subprocess.CompletedProcess([], 0, b"", b"")):
                with self.assertRaisesRegex(screenshot.CaptureError, "No preview"):
                    screenshot.preview_frame(source, 10)
            with mock.patch.object(screenshot.subprocess, "run",
                                   side_effect=subprocess.TimeoutExpired("ffmpeg", 12)):
                with self.assertRaisesRegex(screenshot.CaptureError, "timed out"):
                    screenshot.preview_frame(source, 10)

    def test_rejects_missing_file_without_launching_ffmpeg(self):
        with tempfile.TemporaryDirectory() as name:
            with mock.patch.object(screenshot.subprocess, "run") as run:
                with self.assertRaises(screenshot.CaptureError):
                    screenshot.capture_frame(Path(name) / "missing.mkv", 10, Path(name))
                run.assert_not_called()

    def test_capture_uses_non_overwrite_and_timeout(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "video.mp4"
            source.write_bytes(b"fake input")
            output = base / "screens"
            calls = []

            def fake_ffmpeg(args, **kwargs):
                calls.append((args, kwargs))
                Path(args[-1]).write_bytes(b"PNG")
                return subprocess.CompletedProcess(args, 0, "", "")

            with mock.patch.object(screenshot.subprocess, "run", side_effect=fake_ffmpeg):
                first = screenshot.capture_frame(source, 12.5, output)
                second = screenshot.capture_frame(source, 12.5, output)
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertNotEqual(first, second)
            self.assertIn("-n", calls[0][0])
            self.assertIn("-nostdin", calls[0][0])
            self.assertEqual(calls[0][1]["timeout"], 30)
            self.assertEqual(calls[0][0][calls[0][0].index("-ss") + 1], "12.5")

    def test_file_checks_do_not_depend_on_path_is_file_mock(self):
        # A leaked mock in another test must not turn a missing input or a
        # missing FFmpeg output into successful screenshots.
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "video.mp4"
            with mock.patch.object(Path, "is_file", return_value=True), \
                 mock.patch.object(screenshot.subprocess, "run") as run:
                with self.assertRaisesRegex(screenshot.CaptureError, "missing"):
                    screenshot.capture_frame(source, 1, base)
                run.assert_not_called()
                source.touch()
                run.return_value = subprocess.CompletedProcess([], 0, "", "")
                with self.assertRaisesRegex(screenshot.CaptureError, "no image"):
                    screenshot.capture_frame(source, 1, base)

    def test_zero_byte_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "video.mp4"
            source.touch()

            def fake_ffmpeg(args, **kwargs):
                Path(args[-1]).touch()
                return subprocess.CompletedProcess(args, 0, "", "")

            with mock.patch.object(screenshot.subprocess, "run", side_effect=fake_ffmpeg):
                with self.assertRaisesRegex(screenshot.CaptureError, "no image"):
                    screenshot.capture_frame(source, 1, base)

    def test_timeout_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "video.mp4"
            source.touch()
            with mock.patch.object(screenshot.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 30)):
                with self.assertRaisesRegex(screenshot.CaptureError, "exceeded"):
                    screenshot.capture_frame(source, 5, base)

    def test_failed_or_empty_image_is_not_success(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name)
            source = base / "video.mp4"
            source.touch()
            with mock.patch.object(screenshot.subprocess, "run", return_value=
                                   subprocess.CompletedProcess([], 0, "", "")):
                with self.assertRaisesRegex(screenshot.CaptureError, "no image"):
                    screenshot.capture_frame(source, 5, base)


if __name__ == "__main__":
    unittest.main()
