"""Embedded cover art for audio tracks (#130)."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import screenshot


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
class CoverArtTests(unittest.TestCase):
    def _run(self, *args):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       check=True)

    def test_extracts_embedded_art_and_rejects_plain_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            art, plain, tagged = root / "a.jpg", root / "p.mp3", root / "t.mp3"
            self._run("-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1", str(art))
            self._run("-f", "lavfi", "-i", "sine=d=1", str(plain))
            self._run("-i", str(plain), "-i", str(art), "-map", "0", "-map", "1",
                      "-c", "copy", "-disposition:v", "attached_pic", str(tagged))
            self.assertTrue(screenshot.cover_art(tagged).startswith(b"\xff\xd8"))
            with self.assertRaises(screenshot.CaptureError):
                screenshot.cover_art(plain)

    def test_missing_source_is_a_capture_error(self):
        with self.assertRaises(screenshot.CaptureError):
            screenshot.cover_art(pathlib.Path("/nonexistent/x.mp3"))


if __name__ == "__main__":
    unittest.main()
