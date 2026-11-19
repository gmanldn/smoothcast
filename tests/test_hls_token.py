"""Only the active HLS generation is served; stale ones are rejected (issue #228)."""
from __future__ import annotations

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import server
import streamer

OLD = "a" * 32
NEW = "b" * 32


class ResourceRuleTests(unittest.TestCase):
    def test_with_a_token_only_that_generation_is_public(self):
        ok = (f"/movie-{NEW}.m3u8", f"/segment-{NEW}-00001.ts", f"/segment-{NEW}-7.ts?x=1")
        for path in ok:
            self.assertTrue(server.public_resource(path, NEW), path)
        stale_or_legacy = (f"/movie-{OLD}.m3u8", f"/segment-{OLD}-00001.ts", "/movie.m3u8",
                           "/segment-00001.ts", f"/movie-{NEW}.m3u8/..", f"/x/movie-{NEW}.m3u8",
                           f"/segment-{NEW}-1.ts.bak", "/session.json", f"/movie-{NEW.upper()}.m3u8")
        for path in stale_or_legacy:
            self.assertFalse(server.public_resource(path, NEW), path)

    def test_without_a_token_the_legacy_rules_are_unchanged(self):
        for path in ("/movie.m3u8", "/segment-00001.ts", f"/movie-{OLD}.m3u8", f"/segment-{OLD}-1.ts"):
            self.assertTrue(server.public_resource(path), path)
        self.assertFalse(server.public_resource("/session.json"))

    def test_token_must_be_32_lowercase_hex(self):
        for bad in ("abc", "g" * 32, "A" * 32, "a" * 31, "a" * 33, "../" + "a" * 29, " " + "a" * 31):
            with self.subTest(token=bad), self.assertRaises(ValueError):
                server.make_policy("192.168.1.50", token=bad)
        self.assertEqual(server.make_policy("192.168.1.50", token=NEW).token, NEW)
        self.assertEqual(server.make_policy("192.168.1.50").token, "")

    def test_policy_round_trips_the_token_and_corrupt_tokens_fail_closed(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            policy = server.make_policy("192.168.1.50", token=NEW)
            server.write_policy(root, policy)
            self.assertEqual(server.load_policy(root), policy)
            (root / server.POLICY_NAME).write_text(
                '{"hosts": ["192.168.1.50"], "any_private": false, "token": "../etc"}')
            self.assertEqual(server.load_policy(root), server.AccessPolicy())   # loopback only
            (root / server.POLICY_NAME).write_text('{"hosts": [], "token": 7}')
            self.assertEqual(server.load_policy(root), server.AccessPolicy())


class HttpTokenTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in (f"movie-{OLD}.m3u8", f"movie-{NEW}.m3u8", "movie.m3u8",
                     f"segment-{OLD}-00001.ts", f"segment-{NEW}-00001.ts", "segment-00001.ts"):
            (self.root / name).write_bytes(name.encode())
        patcher = mock.patch.object(server, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def status(self, path: str, method: str = "GET") -> int:
        conn = HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=3)
        try:
            conn.request(method, path)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def activate(self, token: str):
        server.write_policy(self.root, server.make_policy(None, token=token))

    def test_active_generation_is_served_and_everything_else_is_404(self):
        self.activate(NEW)
        for method in ("GET", "HEAD"):
            self.assertEqual(self.status(f"/movie-{NEW}.m3u8", method), 200)
            self.assertEqual(self.status(f"/segment-{NEW}-00001.ts", method), 200)
            self.assertEqual(self.status(f"/movie-{OLD}.m3u8", method), 404)      # wrong token
            self.assertEqual(self.status(f"/segment-{OLD}-00001.ts", method), 404)
            self.assertEqual(self.status("/movie.m3u8", method), 404)            # legacy fixed name
            self.assertEqual(self.status("/segment-00001.ts", method), 404)

    def test_starting_a_new_cast_instantly_invalidates_the_previous_urls(self):
        self.activate(OLD)
        self.assertEqual(self.status(f"/movie-{OLD}.m3u8"), 200)
        self.activate(NEW)                       # next cast; files of OLD still on disk
        self.assertEqual(self.status(f"/movie-{OLD}.m3u8"), 404)
        self.assertEqual(self.status(f"/movie-{NEW}.m3u8"), 200)

    def test_health_check_is_unaffected_by_the_token(self):
        self.activate(NEW)
        self.assertEqual(self.status(server.HEALTH_PATH), 200)

    def test_no_policy_keeps_older_casts_working(self):
        self.assertEqual(self.status("/movie.m3u8"), 200)
        self.assertEqual(self.status(f"/movie-{OLD}.m3u8"), 200)


class StreamerIntegrationTests(unittest.TestCase):
    def start_server(self, root: Path, token: str):
        session = streamer.Session()
        proc = mock.MagicMock(pid=5)
        proc.poll.return_value = None
        with mock.patch.object(streamer, "ROOT", root), \
             mock.patch.object(streamer, "_port_open", return_value=False), \
             mock.patch.object(streamer, "_server_healthy", return_value=True), \
             mock.patch.object(streamer.subprocess, "Popen", return_value=proc):
            session._start_server("192.168.1.23", "192.168.1.50", token=token)
        return session

    def stop(self, root: Path, session) -> None:
        with mock.patch.object(streamer, "ROOT", root), \
             mock.patch.object(streamer, "clear_session"), \
             mock.patch.object(streamer, "_terminate"):
            session.stop("TV", send_stop=False)

    def test_start_publishes_the_generation_and_stop_revokes_it(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            session = self.start_server(root, NEW)
            session._playlist_name = f"movie-{NEW}.m3u8"
            self.assertEqual(server.load_policy(root).token, NEW)
            self.stop(root, session)
            self.assertFalse((root / server.POLICY_NAME).exists())

    def test_stopping_an_older_session_never_revokes_a_newer_casts_policy(self):
        # App flow: new cast starts (new generation published), then the old
        # session is stopped. The new receiver must stay authorised.
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            old_session = streamer.Session()
            old_session._playlist_name = f"movie-{OLD}.m3u8"
            self.start_server(root, NEW)                      # newer cast's policy
            self.stop(root, old_session)
            self.assertEqual(server.load_policy(root).token, NEW)
            self.assertTrue(server.client_allowed("192.168.1.50", server.load_policy(root)))

    def test_session_without_a_generation_never_deletes_the_policy(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.start_server(root, NEW)
            self.stop(root, streamer.Session())               # direct-play / legacy session
            self.assertEqual(server.load_policy(root).token, NEW)

    def test_start_transcode_passes_its_new_generation_to_the_server(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "movie.mp4").write_bytes(b"x")
            media = streamer.MediaInfo(path=root / "movie.mp4", duration=60.0)
            session = streamer.Session()
            session.used_software_fallback = True
            proc = mock.MagicMock(pid=5)
            proc.poll.return_value = None
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.23"), \
                 mock.patch.object(session, "_start_server") as start, \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(session, "_await_receiver"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc):
                session.start_transcode(
                    media, 0.0, device="TV", device_ip="192.168.1.50", quality="balanced",
                    audio_profile="original", subs_file=None, burn_subs=False, title="Film")
            token = start.call_args.kwargs["token"]
            self.assertRegex(token, r"^[0-9a-f]{32}$")
            self.assertEqual(session._playlist_name, f"movie-{token}.m3u8")
            self.assertIn(f"/movie-{token}.m3u8", session.state.stream_url)


if __name__ == "__main__":
    unittest.main()
