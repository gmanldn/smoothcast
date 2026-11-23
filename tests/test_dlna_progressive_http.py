"""Conformance of the DLNA progressive-file HTTP endpoint (issue #43).

A real ProgressiveFileServer on loopback with a small file: HEAD/GET parity, the
DLNA transfer headers, every byte-range shape the server accepts or refuses, the
client allowlist, and that nothing is served once the server is closed. No TV,
no network beyond 127.0.0.0/8.
"""
from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
import socket
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import dlna

DATA = bytes(range(256)) * 4          # 1024 bytes, every byte value known
SIZE = len(DATA)


class ProgressiveHttpTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "film.mp4"
        self.path.write_bytes(DATA)
        self.server = dlna.ProgressiveFileServer(self.path, receiver_ip="192.168.12.25")
        self.addCleanup(self.server.close)
        self.resource = "/media/" + self.server.token

    def request(self, method, path=None, headers=None, source=None):
        conn = HTTPConnection("127.0.0.1", self.server.port, timeout=3,
                              source_address=(source, 0) if source else None)
        try:
            conn.request(method, path or self.resource, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    # -- DLNA headers and HEAD parity -------------------------------------------
    def test_dlna_headers_are_on_every_successful_response(self):
        for method, headers in (("GET", {}), ("HEAD", {}), ("GET", {"Range": "bytes=0-9"}),
                                ("HEAD", {"Range": "bytes=5-"})):
            with self.subTest(method=method, headers=headers):
                status, got, _ = self.request(method, headers=headers)
                self.assertIn(status, (200, 206))
                self.assertEqual(got["Content-Type"], "video/mp4")
                self.assertEqual(got["Accept-Ranges"], "bytes")
                self.assertEqual(got["transferMode.dlna.org"], "Streaming")
                features = got["contentFeatures.dlna.org"]
                self.assertIn("DLNA.ORG_OP=01", features.split(";"))      # byte ranges supported
                flags = dict(p.split("=", 1) for p in features.split(";"))["DLNA.ORG_FLAGS"]
                self.assertRegex(flags, r"^[0-9A-Fa-f]{32}$")             # 8 flag digits + 24 reserved

    def test_head_matches_get_without_a_body(self):
        for rng in (None, "bytes=10-19", "bytes=-5", "bytes=1000-"):
            with self.subTest(range=rng):
                headers = {"Range": rng} if rng else {}
                get_status, get_headers, get_body = self.request("GET", headers=headers)
                head_status, head_headers, head_body = self.request("HEAD", headers=headers)
                self.assertEqual(head_status, get_status)
                self.assertEqual(head_body, b"")
                self.assertEqual(head_headers["Content-Length"], str(len(get_body)))
                for name in ("Content-Type", "Accept-Ranges", "Content-Range",
                             "transferMode.dlna.org", "contentFeatures.dlna.org"):
                    self.assertEqual(head_headers.get(name), get_headers.get(name), name)

    # -- ranges ---------------------------------------------------------------------
    def test_every_accepted_range_shape_returns_exactly_the_requested_bytes(self):
        cases = {
            "bytes=0-0": (0, 0), "bytes=10-19": (10, 19), "bytes=1023-1023": (1023, 1023),
            "bytes=1000-": (1000, 1023), "bytes=0-": (0, 1023), "bytes=-5": (1019, 1023),
            "bytes=-1024": (0, 1023), "bytes=-5000": (0, 1023),           # suffix longer than the file
            "bytes=100-5000": (100, 1023),                                  # end clamped to the file
        }
        for header, (first, last) in cases.items():
            with self.subTest(range=header):
                status, got, body = self.request("GET", headers={"Range": header})
                self.assertEqual(status, 206)
                self.assertEqual(body, DATA[first:last + 1])
                self.assertEqual(got["Content-Range"], f"bytes {first}-{last}/{SIZE}")
                self.assertEqual(got["Content-Length"], str(last - first + 1))

    def test_unsatisfiable_or_malformed_ranges_are_416_with_the_file_size(self):
        for header in ("bytes=1024-", "bytes=2000-3000", "bytes=5-4", "bytes=-0", "bytes=-",
                       "bytes=abc", "items=0-1", "bytes=0-1,5-6", "bytes= 0-1", "0-1", "bytes=--1"):
            with self.subTest(range=header):
                status, got, body = self.request("GET", headers={"Range": header})
                self.assertEqual(status, 416)
                self.assertEqual(got["Content-Range"], f"bytes */{SIZE}")
                self.assertEqual(body, b"")
        self.assertEqual(self.request("GET")[0], 200)                    # still healthy afterwards

    def test_full_response_has_an_exact_content_length(self):
        status, got, body = self.request("GET")
        self.assertEqual((status, body, got["Content-Length"]), (200, DATA, str(SIZE)))
        self.assertNotIn("Content-Range", got)

    def test_a_file_that_changed_size_is_served_with_its_current_length(self):
        self.path.write_bytes(DATA + b"tail")
        status, got, body = self.request("GET")
        self.assertEqual((status, len(body), got["Content-Length"]), (200, SIZE + 4, str(SIZE + 4)))

    # -- the allowlisted session resource ---------------------------------------------
    def test_only_the_session_resource_exists_for_every_method(self):
        for target in ("/", "/media", "/media/", self.resource + "/", self.resource + "x",
                       "/media/" + self.server.token[:-1], "/MEDIA/" + self.server.token,
                       "/media/../media/" + self.server.token,
                       self.resource + "?x=1", self.resource + "#f", "/session.json"):
            for method in ("GET", "HEAD"):
                with self.subTest(target=target, method=method):
                    self.assertEqual(self.request(method, target)[0], 404)

    def test_a_doubled_leading_slash_is_the_same_single_resource_not_a_new_one(self):
        # http.server collapses a leading "//" to "/" (its open-redirect guard): the
        # token is still required and it is the same file, so nothing extra is exposed.
        status, _, body = self.request("GET", "//media/" + self.server.token)
        self.assertEqual((status, body), (200, DATA))
        self.assertEqual(self.request("GET", "//media/wrong")[0], 404)
        self.assertEqual(self.request("GET", "//")[0], 404)

    def test_other_methods_do_not_serve_the_file(self):
        for method in ("POST", "PUT", "DELETE", "OPTIONS", "PATCH"):
            with self.subTest(method=method):
                status, _, body = self.request(method)
                self.assertGreaterEqual(status, 400)
                self.assertNotEqual(body, DATA)

    def test_clients_other_than_the_receiver_or_loopback_get_404_even_with_the_token(self):
        try:
            status, _, body = self.request("GET", source="127.0.0.2")
        except OSError:
            self.skipTest("this platform has no 127.0.0.2 loopback alias")
        self.assertEqual(status, 404)
        self.assertNotEqual(body, DATA)

    def test_the_token_is_unguessable_and_unique_per_server(self):
        other = dlna.ProgressiveFileServer(self.path, receiver_ip="192.168.12.25")
        self.addCleanup(other.close)
        self.assertNotEqual(other.token, self.server.token)
        self.assertGreaterEqual(len(self.server.token), 24)
        self.assertEqual(self.request("GET", "/media/" + other.token)[0], 404)

    def test_nothing_is_served_after_close(self):
        self.assertEqual(self.request("GET")[0], 200)
        self.server.close()
        with self.assertRaises(OSError):
            self.request("GET")

    def test_a_dropped_client_does_not_kill_the_server(self):
        raw = socket.create_connection(("127.0.0.1", self.server.port), timeout=3)
        raw.sendall(f"GET {self.resource} HTTP/1.1\r\nHost: 127.0.0.1:{self.server.port}\r\n\r\n".encode())
        raw.close()                                                        # hang up before reading
        self.assertEqual(self.request("GET")[0], 200)


if __name__ == "__main__":
    unittest.main()
