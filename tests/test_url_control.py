"""Remote URL classification and validation (no GTK or network required)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import url_control
from url_control import classify_media_url, validate_media_url


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


class SitePageTests(unittest.TestCase):
    def test_known_site_pages_are_rejected_with_the_site_name_and_remedy(self):
        for url, site in (
            ("https://www.youtube.com/watch?v=abc", "YouTube"),
            ("https://youtu.be/abc", "YouTube"),
            ("https://m.youtube.com/watch?v=abc", "YouTube"),
            ("https://vimeo.com/12345", "Vimeo"),
            ("https://www.netflix.com/title/1", "Netflix"),
        ):
            with self.subTest(url=url):
                with self.assertRaises(url_control.MediaUrlError) as caught:
                    validate_media_url(url)
                message = str(caught.exception)
                self.assertIn(site, message)
                self.assertIn("direct HTTP(S) media URL", message)
                self.assertIn("download", message)

    def test_site_detection_does_not_match_unrelated_suffixes(self):
        self.assertEqual(
            validate_media_url("https://notyoutube.com/film.mp4"),
            "https://notyoutube.com/film.mp4",
        )
        self.assertEqual(
            validate_media_url("https://youtube.com.example.net/film.mp4"),
            "https://youtube.com.example.net/film.mp4",
        )


class ClassificationTests(unittest.TestCase):
    def test_media_suffix_is_classified_as_direct(self):
        for url in (
            "https://cdn.example.com/film.MP4",
            "https://cdn.example.com/live.m3u8?token=1",
            "http://192.168.1.2:8000/audio.flac",
        ):
            with self.subTest(url=url):
                result = classify_media_url(url)
                self.assertTrue(result.is_direct)
                self.assertEqual(result.url, url)

    def test_unknown_suffix_is_allowed_but_not_claimed_as_direct(self):
        result = classify_media_url("https://media.example.com/stream/42")
        self.assertFalse(result.is_direct)
        self.assertEqual(result.kind, "unknown")
        self.assertEqual(validate_media_url(result.url), result.url)

    def test_non_raising_helper(self):
        self.assertTrue(url_control.is_direct_media_url("https://example.com/a.webm"))
        self.assertFalse(url_control.is_direct_media_url("https://youtube.com/watch?v=1"))
        self.assertFalse(url_control.is_direct_media_url("file:///tmp/a.mp4"))


if __name__ == "__main__":
    unittest.main()