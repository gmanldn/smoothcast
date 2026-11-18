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
