"""Bounded HLS server log, included in diagnostics (issue #232)."""
from __future__ import annotations

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import diagnostics
import error_log
import server


class ServerLogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "movie.m3u8").write_text("#EXTM3U\n")
        for patcher in (mock.patch.object(server, "ROOT", self.root),
                        mock.patch.dict(server._LOGS, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    @property
    def log_path(self) -> Path:
        return self.root / server.LOG_NAME

    def get(self, path: str) -> int:
        conn = HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=3)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def lines(self) -> list[str]:
        return self.log_path.read_text("utf-8").splitlines() if self.log_path.exists() else []

    def test_unparsable_request_target_is_a_404_not_a_dropped_connection(self):
        import socket
        for target in ("//a]b", "//[::1", "//x]/movie.m3u8"):
            with self.subTest(target=target), socket.create_connection(
                    ("127.0.0.1", self.httpd.server_address[1]), timeout=3) as sock:
                sock.sendall(f"GET {target} HTTP/1.0\r\n\r\n".encode())
                status = sock.makefile("rb").readline()
                self.assertIn(b" 404 ", status)
        self.assertFalse(server.public_resource("//a]b"))

    def test_failed_requests_are_logged_but_successful_ones_are_not(self):
        self.assertEqual(self.get("/movie.m3u8"), 200)
        self.assertEqual(self.get(server.HEALTH_PATH), 200)
        self.assertEqual(self.lines(), [])                 # a whole film of 200s stays silent
        self.assertEqual(self.get("/session.json"), 404)
        text = "\n".join(self.lines())
        self.assertIn("404", text)
        self.assertIn("127.0.0.1", text)

    def test_denied_clients_are_logged_with_their_status(self):
        with mock.patch.object(server, "client_allowed", return_value=False):
            self.assertEqual(self.get("/movie.m3u8"), 403)
        self.assertIn("403", "\n".join(self.lines()))

    def test_log_reuses_the_error_log_limits_and_stays_bounded(self):
        self.assertIsInstance(server.server_log(), error_log.ErrorLog)
        with mock.patch.object(error_log, "MAX_LOG_BYTES", 4096), \
             mock.patch.object(error_log, "MAX_RETAIN_BYTES", 2048):
            for index in range(400):
                self.get(f"/missing-{index}.ts")
            size = self.log_path.stat().st_size
        self.assertLessEqual(size, 4096 + 512)             # limit plus one entry of slack
        self.assertIn("missing-399", self.log_path.read_text("utf-8"))  # newest kept

    def test_one_log_instance_per_file_across_threads(self):
        self.assertIs(server.server_log(), server.server_log())

    def test_unwritable_log_never_breaks_streaming(self):
        self.log_path.mkdir()                              # a directory where the file should be
        self.assertEqual(self.get("/session.json"), 404)   # logging fails silently
        self.assertEqual(self.get("/movie.m3u8"), 200)

    def test_bind_failure_is_recorded_before_the_error_propagates(self):
        with mock.patch.object(server, "ThreadingHTTPServer", side_effect=OSError("in use")):
            with self.assertRaises(OSError):
                server.main(["--bind", "127.0.0.1"])
        text = "\n".join(self.lines())
        self.assertIn("cannot listen", text)
        self.assertIn("in use", text)

    def test_startup_event_is_logged(self):
        fake = mock.MagicMock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(server, "ThreadingHTTPServer", return_value=fake):
            with self.assertRaises(KeyboardInterrupt):
                server.main([])
        self.assertIn("listening on 127.0.0.1", "\n".join(self.lines()))


class DiagnosticsIntegrationTests(unittest.TestCase):
    def test_bundle_includes_the_redacted_bounded_server_log_tail(self):
        with tempfile.TemporaryDirectory() as work:
            log = Path(work) / "server.log"
            log.write_text("\n".join(
                f"2026-11-19T10:00:00  127.0.0.1 code 404, message /home/alice/film-{i}.mkv"
                for i in range(diagnostics.MAX_SERVER_LINES + 30)) + "\n")
            with mock.patch.object(diagnostics, "tool_version", return_value=""):
                payload = diagnostics.collect(server_log=log, home="/home/alice")
        lines = payload["server_log"]
        self.assertEqual(len(lines), diagnostics.MAX_SERVER_LINES)
        self.assertTrue(all("alice" not in line for line in lines))
        self.assertIn("film-129", lines[-1])               # the newest lines are kept

    def test_missing_server_log_is_an_empty_list_and_default_path_is_the_cache_dir(self):
        with mock.patch.object(diagnostics, "tool_version", return_value=""):
            payload = diagnostics.collect(server_log=Path("/nonexistent/server.log"))
        self.assertEqual(payload["server_log"], [])
        self.assertEqual(diagnostics.default_server_log_path(),
                         Path.home() / ".cache" / "cast-control" / "server.log")

    def test_export_writes_the_server_log_section(self):
        with tempfile.TemporaryDirectory() as work:
            log = Path(work) / "server.log"
            log.write_text("2026-11-19T10:00:00  listening on 127.0.0.1 port 8767\n")
            with mock.patch.object(diagnostics, "tool_version", return_value=""):
                bundle = diagnostics.export(destination=Path(work) / "bundle.json",
                                            error_log=Path(work) / "none.log", server_log=log)
            self.assertIn("listening on", bundle.read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
