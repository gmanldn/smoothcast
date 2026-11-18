"""Remote URL validation regression tests (no GTK or network required)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from url_control import validate_media_url


class UrlValidationTests(unittest.TestCase):
    def test_http_and_https_urls_accepted(self):
        self.assertEqual(
            validate_media_url("  https://example.com/video.mp4?token=abc  "),
            "https://example.com/video.mp4?token=abc",
        )
        self.assertEqual(validate_media_url("http://192.168.1.5:8000/clip"), "http://192.168.1.5:8000/clip")

    def test_local_paths_and_non_web_schemes_rejected(self):
        for url in ("/home/user/movie.mp4", "file:///tmp/a.mkv", "javascript:alert(1)", ""):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_media_url(url)

    def test_invalid_hosts_ports_and_whitespace_rejected(self):
        for url in ("https://", "http://example.com:abcd/video", "https://exa mple.com/video",
                    "https://[::1/video", "https://example.com/line\nfeed"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_media_url(url)

    def test_embedded_credentials_rejected(self):
        with self.assertRaises(ValueError):
            validate_media_url("https://alice:password@example.com/private.mp4")


if __name__ == "__main__":
    unittest.main()
