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

    def test_playlists_and_segments_send_no_cors_wildcard(self):
        # A page on the network must not be able to read the stream through
        # CORS; receivers use native media fetches that ignore it (issue #229).
        for path in ("/movie.m3u8", "/segment-00000.ts"):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    status, _, headers = self.request(path, method)
                    self.assertEqual(status, 200)
                    headers_ci = {name.lower(): value for name, value in headers.items()}
                    self.assertNotIn("access-control-allow-origin", headers_ci)
                    self.assertEqual(headers_ci.get("cache-control"), "no-store")
    def test_hls_content_types_and_lengths_are_stable_for_get_and_head(self):
        samples = (
            ("/movie.m3u8", "application/vnd.apple.mpegurl",
             (self.root / "movie.m3u8").read_bytes()),
            ("/segment-00000.ts", "video/mp2t", b"mpeg-ts"),
        )
        # Test the actual HTTP handler, not just a platform MIME lookup.
        for path, content_type, payload in samples:
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    status, body, headers = self.request(path, method)
                    self.assertEqual(status, 200)
                    headers_ci = {name.lower(): value for name, value in headers.items()}
                    self.assertEqual(headers_ci.get("content-type"), content_type)
                    self.assertEqual(int(headers_ci["content-length"]), len(payload))
                    self.assertEqual(headers_ci["cache-control"], "no-store")
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

    def test_clients_outside_the_policy_get_403_but_loopback_is_allowed(self):
        # Loopback is always allowed: the health check and our own tests.
        self.assertEqual(self.request("/movie.m3u8")[0], 200)
        denied = server.AccessPolicy()
        with mock.patch.object(server, "client_allowed", return_value=False) as check:
            for method in ("GET", "HEAD"):
                for path in ("/movie.m3u8", "/segment-00000.ts", server.HEALTH_PATH,
                             "/session.json"):
                    with self.subTest(method=method, path=path):
                        self.assertEqual(self.request(path, method)[0], 403)
            self.assertTrue(check.called)
        self.assertFalse(server.client_allowed("203.0.113.9", denied))

    def test_health_reports_bind_address_and_pid_for_reuse_decisions(self):
        _, _, headers = self.request(server.HEALTH_PATH)
        lowered = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(lowered["x-smoothcast-pid"], str(__import__("os").getpid()))
        self.assertIn("x-smoothcast-bind", lowered)

    def test_health_endpoint_identifies_our_server(self):
        status, body, _ = self.request(server.HEALTH_PATH)
        self.assertEqual((status, body), (200, server.HEALTH_BODY))
        status, body, _ = self.request(server.HEALTH_PATH, "HEAD")
        self.assertEqual((status, body), (200, b""))


class AccessPolicyTests(unittest.TestCase):
    RECEIVER = server.make_policy("192.168.1.50")

    def test_receiver_and_loopback_only(self):
        for address in ("192.168.1.50", "127.0.0.1", "::1", "127.0.0.2"):
            with self.subTest(address=address):
                self.assertTrue(server.client_allowed(address, self.RECEIVER))
        for address in ("192.168.1.51", "10.0.0.5", "169.254.1.1", "garbage", ""):
            with self.subTest(address=address):
                self.assertFalse(server.client_allowed(address, self.RECEIVER))

    def test_public_addresses_are_never_allowed(self):
        for address in ("8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"):
            self.assertFalse(server.client_allowed(address, self.RECEIVER))
            self.assertFalse(server.client_allowed(address, server.make_policy(None)))
        # A public "receiver" can be named explicitly but is not private-LAN.
        self.assertFalse(server.client_allowed("8.8.8.8", server.make_policy("garbage")))

    def test_ipv4_mapped_ipv6_follows_the_ipv4_rules(self):
        self.assertTrue(server.client_allowed("::ffff:192.168.1.50", self.RECEIVER))
        self.assertTrue(server.client_allowed("::ffff:127.0.0.1", self.RECEIVER))
        self.assertFalse(server.client_allowed("::ffff:8.8.8.8", self.RECEIVER))
        self.assertFalse(server.client_allowed("::ffff:192.168.1.51", self.RECEIVER))

    def test_unknown_receiver_falls_back_to_private_lan_not_public(self):
        policy = server.make_policy(None)
        self.assertTrue(policy.any_private)
        for address in ("192.168.0.9", "10.1.2.3", "172.16.4.4", "127.0.0.1"):
            self.assertTrue(server.client_allowed(address, policy), address)
        for address in ("8.8.8.8", "100.64.0.1"):
            self.assertFalse(server.client_allowed(address, policy), address)

    def test_extra_allowed_addresses_must_be_private(self):
        policy = server.make_policy("192.168.1.50", ("192.168.1.60", "8.8.8.8", "x"))
        self.assertTrue(server.client_allowed("192.168.1.60", policy))
        self.assertFalse(server.client_allowed("8.8.8.8", policy))

    def test_policy_round_trips_and_missing_or_corrupt_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.assertEqual(server.load_policy(root), server.AccessPolicy())
            server.write_policy(root, self.RECEIVER)
            self.assertEqual(server.load_policy(root), self.RECEIVER)
            (root / server.POLICY_NAME).write_text("{not json")
            self.assertEqual(server.load_policy(root), server.AccessPolicy())
            self.assertFalse(server.client_allowed("192.168.1.50", server.load_policy(root)))

    def test_listen_addresses_never_include_the_wildcard(self):
        for bind in (None, "", "0.0.0.0", "::", "224.0.0.1", "bad", "::1"):
            self.assertEqual(server._listen_addresses(bind), ["127.0.0.1"], bind)
        self.assertEqual(server._listen_addresses("192.168.1.23"), ["127.0.0.1", "192.168.1.23"])


if __name__ == "__main__":
    unittest.main()
