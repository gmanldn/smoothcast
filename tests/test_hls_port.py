"""Configurable HLS port with automatic fallback (issue #231)."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import cache_policy
import config_control
import network_routes
import server
import streamer

IP = "192.168.1.23"


class PortHelperTests(unittest.TestCase):
    def test_single_source_of_truth_for_the_default_port(self):
        self.assertEqual(streamer.PORT, server.PORT)
        self.assertEqual(streamer.PORT, 8767)

    def test_candidates_start_with_the_preferred_port_without_duplicates(self):
        default = streamer.candidate_ports()
        self.assertEqual(default[0], 8767)
        self.assertEqual(len(default), streamer.FALLBACK_PORTS)
        custom = streamer.candidate_ports(9000)
        self.assertEqual(custom[0], 9000)
        self.assertEqual(custom[1:], default)               # then the whole fallback range
        inside = streamer.candidate_ports(8770)
        self.assertEqual(inside[0], 8770)
        self.assertEqual(len(inside), len(set(inside)))
        self.assertEqual(len(inside), streamer.FALLBACK_PORTS)

    def test_invalid_preferred_ports_fall_back_to_the_default(self):
        for bad in (0, 80, 1023, 65536, -1, "8767", None, 8767.0, True):
            with self.subTest(bad=bad):
                self.assertEqual(streamer.candidate_ports(bad)[0], 8767)  # type: ignore[arg-type]

    def test_configured_port_is_read_validated_and_never_raises(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "config.json"
            with mock.patch.object(cache_policy, "config_path", return_value=path):
                self.assertEqual(streamer.configured_hls_port(), 8767)   # no file
                for text, expected in ((json.dumps({"hls_port": 9100}), 9100),
                                       (json.dumps({"hls_port": 80}), 8767),
                                       (json.dumps({"hls_port": "9100"}), 8767),
                                       (json.dumps({"hls_port": True}), 8767),
                                       (json.dumps([1]), 8767), ("{bad", 8767)):
                    path.write_text(text)
                    self.assertEqual(streamer.configured_hls_port(), expected, text)
                path.write_text(json.dumps({"hls_port": 9100}))
                self.assertEqual(streamer.Session().port, 9100)           # picked up by Session
                self.assertEqual(streamer.Session(port=9200).port, 9200)  # explicit wins
                self.assertEqual(streamer.Session(port=22).port, 9100)    # invalid explicit ignored

    def test_setting_is_persisted_and_validated_by_the_config_loader(self):
        defaults = {"hls_port": 8767}
        for good in (1024, 8767, 65535):
            self.assertEqual(config_control.sanitise_config({"hls_port": good}, defaults)["hls_port"], good)
        for bad in (0, 1023, 65536, "x", 1.5, True, None):
            self.assertEqual(config_control.sanitise_config({"hls_port": bad}, defaults)["hls_port"], 8767)
        self.assertIn('"hls_port": 8767', (ROOT / "src" / "cast_widgets.py").read_text("utf-8"))

    def test_server_accepts_a_valid_port_argument_only(self):
        self.assertEqual(server.listen_port([]), 8767)
        self.assertEqual(server.listen_port(["--port", "9100"]), 9100)
        for bad in (["--port", "80"], ["--port", "x"], ["--port"], ["--port", "70000"]):
            self.assertEqual(server.listen_port(bad), 8767, bad)

    def test_server_main_listens_on_the_requested_port(self):
        fake = mock.MagicMock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(server, "ThreadingHTTPServer", return_value=fake) as factory, \
             mock.patch.object(server, "log_event"):
            with self.assertRaises(KeyboardInterrupt):
                server.main(["--port", "9100", "--bind", "127.0.0.1"])
        self.assertEqual(factory.call_args.args[0], ("127.0.0.1", 9100))

    def test_real_probe_identifies_our_server_on_any_port(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        port = httpd.server_address[1]
        healthy, bound, pid = streamer._server_probe(port)
        self.assertTrue(healthy)
        self.assertTrue(streamer._server_healthy(port))
        self.assertTrue(streamer._port_open(port))
        self.assertFalse(streamer._server_probe(port + 1)[0] and streamer._port_open(port + 1))


class PortSelectionTests(unittest.TestCase):
    def start(self, *, open_ports=(), healthy=None, port=None, bind=IP):
        """Run the real _start_server with fake listeners: {port: (bound, pid)} for ours."""
        healthy = healthy or {}
        session = streamer.Session(port=port)
        proc = mock.MagicMock(pid=999)
        proc.poll.return_value = None
        with tempfile.TemporaryDirectory() as work, \
             mock.patch.object(streamer, "ROOT", Path(work)), \
             mock.patch.object(streamer, "_port_open", side_effect=lambda p: p in open_ports), \
             mock.patch.object(streamer, "_server_probe",
                               side_effect=lambda p: (p in healthy, *(healthy.get(p) or (None, None)))), \
             mock.patch.object(streamer, "_server_healthy", return_value=True), \
             mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
            error = None
            try:
                session._start_server(bind, "192.168.1.50")
            except streamer.StreamError as exc:
                error = exc
        return session, popen, error

    def test_free_preferred_port_is_used_and_passed_to_the_server(self):
        session, popen, error = self.start()
        self.assertIsNone(error)
        self.assertEqual(session.port, 8767)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--port") + 1], "8767")
        self.assertEqual(command[-2:], ["--bind", IP])

    def test_port_held_by_another_program_falls_back_to_the_next_free_one(self):
        session, popen, error = self.start(open_ports={8767, 8768})   # neither is ours
        self.assertIsNone(error)
        self.assertEqual(session.port, 8769)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--port") + 1], "8769")

    def test_configured_port_is_preferred_then_the_range_is_used(self):
        session, popen, _ = self.start(port=9100)
        self.assertEqual(session.port, 9100)
        session, popen, _ = self.start(port=9100, open_ports={9100})
        self.assertEqual(session.port, 8767)

    def test_a_kept_server_on_a_fallback_port_is_reused_not_orphaned(self):
        session, popen, error = self.start(open_ports={8769}, healthy={8769: (IP, 4242)})
        self.assertIsNone(error)
        self.assertEqual(session.port, 8769)       # even though 8767 is free
        popen.assert_not_called()

    def test_kept_server_on_another_interface_is_replaced_on_its_own_port(self):
        calls = iter([True, False])                # port open, then freed after termination
        session = streamer.Session()
        proc = mock.MagicMock(pid=1)
        proc.poll.return_value = None
        with tempfile.TemporaryDirectory() as work, \
             mock.patch.object(streamer, "ROOT", Path(work)), \
             mock.patch.object(streamer, "_port_open", side_effect=lambda p: next(calls) if p == 8768 else False), \
             mock.patch.object(streamer, "_server_probe", return_value=(True, "10.9.9.9", 4242)), \
             mock.patch.object(streamer, "_pid_is_ours", return_value=True), \
             mock.patch.object(streamer, "_terminate_pid") as terminate, \
             mock.patch.object(streamer, "_server_healthy", return_value=True), \
             mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
            with mock.patch.object(streamer, "candidate_ports", return_value=[8768, 8769]):
                session._start_server(IP, "192.168.1.50")
        terminate.assert_called_once_with(4242, "server")
        self.assertEqual(session.port, 8768)
        self.assertEqual(popen.call_args.args[0][popen.call_args.args[0].index("--port") + 1], "8768")

    def test_every_port_taken_gives_a_clear_error_and_starts_nothing(self):
        everything = set(range(streamer.PORT, streamer.PORT + streamer.FALLBACK_PORTS))
        session, popen, error = self.start(open_ports=everything)
        self.assertIsNotNone(error)
        self.assertIn("occupied", str(error))
        self.assertIn("8767", str(error))
        popen.assert_not_called()

    def test_stream_url_uses_the_port_actually_chosen(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "movie.mp4").write_bytes(b"x")
            media = streamer.MediaInfo(path=root / "movie.mp4", duration=60.0)
            session = streamer.Session()
            session.used_software_fallback = True
            proc = mock.MagicMock(pid=5)
            proc.poll.return_value = None

            def choose_port(*_args, **_kwargs):
                session.port = 8771
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value=IP), \
                 mock.patch.object(session, "_start_server", side_effect=choose_port), \
                 mock.patch.object(session, "_wait_for_segments", return_value=True), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 0.0, device="TV", device_ip="192.168.1.50", quality="balanced",
                    audio_profile="original", subs_file=None, burn_subs=False, title="Film")
            self.assertIn(f"{IP}:8771/", session.state.stream_url)
            cast_args = popen.call_args_list[-1].args[0]
            self.assertTrue(any(":8771/" in str(arg) for arg in cast_args))   # catt gets the same URL


class NetworkCheckTests(unittest.TestCase):
    def state(self, url):
        return mock.Mock(stream_url=url)

    def test_active_port_comes_from_the_saved_session_url(self):
        with mock.patch.object(streamer, "load_session", return_value=self.state("http://192.168.1.2:8775/m.m3u8")):
            self.assertEqual(network_routes.active_port(), 8775)
        for bad in (self.state(""), self.state("http://x/y"), self.state("http://x:22/y"), None):
            with self.subTest(bad=bad), mock.patch.object(streamer, "load_session", return_value=bad):
                self.assertEqual(network_routes.active_port(), 8767)
        with mock.patch.object(streamer, "load_session", side_effect=OSError):
            self.assertEqual(network_routes.active_port(), 8767)

    def test_report_checks_and_advertises_the_active_port(self):
        opened = []

        def open_url(url, timeout):
            opened.append(url)
            raise OSError
        with mock.patch.object(streamer, "load_session", return_value=self.state("http://192.168.1.2:8775/m.m3u8")):
            sock = mock.MagicMock()
            sock.__enter__.return_value.getsockname.return_value = ("192.168.1.2", 1)
            result = network_routes.report("192.168.1.50", socket_factory=lambda *a, **k: sock,
                                           connect=mock.MagicMock(), open_url=open_url,
                                           run=mock.Mock(side_effect=OSError), os_name="Linux")
        self.assertEqual(opened, ["http://127.0.0.1:8775/_smoothcast/health"])
        self.assertEqual(result["second_host_health_url"], "http://192.168.1.2:8775/_smoothcast/health")


if __name__ == "__main__":
    unittest.main()
