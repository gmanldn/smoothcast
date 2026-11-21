"""HTTP regression tests: cast media public, session metadata private."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import os
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
            ("movie-" + "a" * 32 + "-fmp4.m3u8"): b"#EXTM3U\n",
            ("segment-" + "a" * 32 + "-00000.m4s"): b"fragmented-mp4",
            ("init-" + "a" * 32 + ".mp4"): b"init-segment",
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

    def request(self, path, method="GET", headers=None):
        conn = HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=3)
        try:
            conn.request(method, path, headers=headers or {})
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

    def test_host_header_rejects_rebinding_on_media_and_health(self):
        allowed = f"127.0.0.1:{self.httpd.server_address[1]}"
        for path in ("/movie.m3u8", "/segment-00000.ts", server.HEALTH_PATH):
            for method in ("GET", "HEAD"):
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.request(path, method, {"Host": allowed})[0], 200)
                    for invalid in ("evil.example", "127.0.0.1.evil.example",
                                    "127.0.0.1:9999", "8.8.8.8"):
                        self.assertEqual(
                            self.request(path, method, {"Host": invalid})[0], 400,
                            (path, method, invalid),
                        )
        self.assertEqual(self.request("/movie.m3u8")[0], 200)

    def test_duplicate_host_headers_are_rejected(self):
        conn = HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=3)
        try:
            conn.putrequest("GET", "/movie.m3u8", skip_host=True)
            conn.putheader("Host", f"127.0.0.1:{self.httpd.server_address[1]}")
            conn.putheader("Host", "evil.example")
            conn.endheaders()
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            conn.close()

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
            ("/segment-" + "a" * 32 + "-00000.m4s", "video/mp4", b"fragmented-mp4"),
            ("/init-" + "a" * 32 + ".mp4", "video/mp4", b"init-segment"),
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

    def test_byte_ranges_are_conformant_for_gets_and_heads(self):
        size = len((self.root / "segment-00000.ts").read_bytes())
        payload = (self.root / "segment-00000.ts").read_bytes()
        cases = {
            "bytes=0-3": (0, 3),
            "bytes=3-": (3, size - 1),
            "bytes=-3": (size - 3, size - 1),
            f"bytes=0-{size * 10}": (0, size - 1),
        }
        for header, (start, end) in cases.items():
            for method in ("GET", "HEAD"):
                with self.subTest(header=header, method=method):
                    status, body, headers = self.request(
                        "/segment-00000.ts", method, {"Range": header})
                    lowered = {k.lower(): v for k, v in headers.items()}
                    self.assertEqual(status, 206)
                    self.assertEqual(lowered["content-range"], f"bytes {start}-{end}/{size}")
                    self.assertEqual(int(lowered["content-length"]), end - start + 1)
                    self.assertEqual(lowered["accept-ranges"], "bytes")
                    self.assertEqual(body, payload[start:end + 1] if method == "GET" else b"")

    def test_unsatisfiable_or_multiple_ranges_are_416_with_the_file_size(self):
        size = len((self.root / "segment-00000.ts").read_bytes())
        for header in ("bytes=99-", "bytes=5-4", "bytes=-0", "bytes=0-1,4-5",
                       "bytes=x-y", "garbage"):
            for method in ("GET", "HEAD"):
                with self.subTest(header=header, method=method):
                    status, body, headers = self.request(
                        "/segment-00000.ts", method, {"Range": header})
                    lowered = {k.lower(): v for k, v in headers.items()}
                    self.assertEqual(status, 416)
                    self.assertEqual(lowered["content-range"], f"bytes */{size}")
                    self.assertEqual(body, b"")

    def test_if_range_ignores_a_stale_validator_and_honours_the_current_one(self):
        _, _, headers = self.request("/segment-00000.ts")
        etag = {k.lower(): v for k, v in headers.items()}["etag"]
        status, body, _ = self.request(
            "/segment-00000.ts", headers={"Range": "bytes=0-1", "If-Range": etag})
        self.assertEqual((status, body), (206, b"mp"))
        status, body, _ = self.request(
            "/segment-00000.ts", headers={"Range": "bytes=0-1", "If-Range": '"old"'})
        self.assertEqual(status, 200)
        self.assertEqual(body, (self.root / "segment-00000.ts").read_bytes())

    def test_missing_or_symlinked_media_is_never_followed(self):
        target = self.root / "segment-00000.ts"
        outside = self.root.parent / "outside.ts"
        outside.write_bytes(b"secret")
        original = target.read_bytes()
        target.unlink()
        try:
            os.symlink(outside, target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        try:
            self.assertEqual(self.request("/segment-00000.ts")[0], 404)
        finally:
            target.unlink()
            target.write_bytes(original)
            outside.unlink(missing_ok=True)

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


class ListenLifecycleTests(unittest.TestCase):
    def test_partial_multibind_failure_closes_first_socket_before_retry(self):
        with tempfile.TemporaryDirectory() as work:
            first = mock.Mock(spec=ThreadingHTTPServer)
            with mock.patch.object(server, "ROOT", Path(work)), \
                 mock.patch.object(server, "_listen_addresses",
                                   return_value=["127.0.0.1", "192.168.1.5"]), \
                 mock.patch.object(server, "ThreadingHTTPServer",
                                   side_effect=[first, OSError("address unavailable")]) as bind, \
                 mock.patch.object(server, "log_event"):
                with self.assertRaisesRegex(OSError, "address unavailable"):
                    server.main(["--port", "8767", "--bind", "192.168.1.5"])
            self.assertEqual(bind.call_count, 2)
            first.server_close.assert_called_once_with()
            first.serve_forever.assert_not_called()


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
