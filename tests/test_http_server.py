"""HTTP regression tests: cast media public, session metadata private."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import server


class StreamServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, content in {
            "movie.m3u8": b"#EXTM3U\n#EXTINF:4,\nsegment-00000.ts\n",
            "segment-00000.ts": b"mpeg-ts",
            "session.json": b'{"file": "/home/private/film.mp4"}',
            "ffmpeg.log": b"private encoder output",
            "burned_subs.srt": b"private subtitles",
        }.items():
            (self.root / name).write_bytes(content)
        patcher = mock.patch.object(server, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 3)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def request(self, path, method="GET"):
        conn = HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=3)
        try:
            conn.request(method, path)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def test_playlists_and_segments_serve_for_chromecast(self):
        status, body, headers = self.request("/movie.m3u8")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"#EXTM3U"))
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        status, body, _ = self.request("/segment-00000.ts")
        self.assertEqual((status, body), (200, b"mpeg-ts"))
        status, body, _ = self.request("/segment-00000.ts", "HEAD")
        self.assertEqual((status, body), (200, b""))

    def test_hls_content_types_and_lengths_are_stable_for_get_and_head(self):
        samples = (
            ("/movie.m3u8", "application/vnd.apple.mpegurl",
             b"#EXTM3U\\n#EXTINF:4,\\nsegment-00000.ts\\n"),
            ("/segment-00000.ts", "video/mp2t", b"mpeg-ts"),
        )
        # Test the actual HTTP handler, not just a platform MIME lookup.
        for path, content_type, payload in samples:
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    status, body, headers = self.request(path, method)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers.get("Content-Type"), content_type)
                    self.assertEqual(int(headers["Content-Length"]), len(payload))
                    self.assertEqual(headers["Cache-Control"], "no-store")
                    self.assertEqual(body, payload if method == "GET" else b"")

    def test_private_files_and_directory_traversal_are_rejected(self):
        for path in (
            "/", "/session.json", "/ffmpeg.log", "/burned_subs.srt",
            "/../session.json", "/%2e%2e/session.json", "/.hidden",
            "/segment-00000.ts/../session.json", "/movie.m3u8%2F..",
        ):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)
                status, _, _ = self.request(path, "HEAD")
                self.assertEqual(status, 404)

    def test_health_endpoint_identifies_our_server(self):
        status, body, _ = self.request(server.HEALTH_PATH)
        self.assertEqual((status, body), (200, server.HEALTH_BODY))
        status, body, _ = self.request(server.HEALTH_PATH, "HEAD")
        self.assertEqual((status, body), (200, b""))


if __name__ == "__main__":
    unittest.main()
