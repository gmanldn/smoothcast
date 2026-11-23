"""Production code against the fake receivers (issue #278): no mocks of dlna/castctl."""
from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

import castctl
import cli_control
import dlna
import playback_state
import playlist_control
import streamer
import fake_receivers
from fake_receivers import FakeCast, FakeDlnaRenderer, allow_loopback

RECEIVER_FAILED = "The receiver command failed. Check the receiver connection and try again."

MEDIA = "http://192.168.1.2:9000/media/token"


class FakeDlnaTests(unittest.TestCase):
    def setUp(self):
        self.tv = FakeDlnaRenderer(duration=600)
        self.tv.start()
        self.addCleanup(self.tv.stop)
        patcher = allow_loopback()
        patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        self.renderer = self.tv.renderer()

    def test_soap_bodies_with_dtds_or_entities_or_excess_size_are_refused(self):
        import urllib.error
        import urllib.request
        url = self.renderer.transport_url
        env = ('<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
               '<u:GetTransportInfo xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
               '<InstanceID>0</InstanceID></u:GetTransportInfo></s:Body></s:Envelope>')

        def post(body: bytes) -> int:
            request = urllib.request.Request(url, data=body, headers={
                "Content-Type": "text/xml",
                "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#GetTransportInfo"'})
            try:
                return urllib.request.urlopen(request, timeout=3).status
            except urllib.error.HTTPError as exc:
                return exc.code

        self.assertEqual(post(env.encode()), 200)  # control: the same action is accepted
        self.assertEqual(post(b'<!DOCTYPE x [<!ENTITY a "a">]>' + env.encode()), 400)
        self.assertEqual(post(b"<!doctype x>" + env.encode()), 400)
        self.assertEqual(post(env.encode() + b" " * (256 * 1024)), 400)

    def test_discovery_description_parses_to_the_same_endpoints(self):
        import urllib.request
        body = urllib.request.urlopen(self.tv.location, timeout=3).read()
        parsed = dlna.parse_renderer(body, self.tv.location, "127.0.0.1")
        self.assertEqual((parsed.name, parsed.model), ("Fake TV", "FakeDMR"))
        self.assertEqual(parsed.transport_url, self.renderer.transport_url)
        self.assertEqual(parsed.rendering_url, self.renderer.rendering_url)

    def test_real_ssdp_msearch_discovery_uses_loopback_fallback(self):
        with mock.patch.object(dlna, "SSDP_ADDRESS", ("127.0.0.1", self.tv.ssdp_port)):
            found = dlna.discover(timeout=0.6)
        self.assertEqual([(item.name, item.host, item.transport_url) for item in found], [
            ("Fake TV", "127.0.0.1", self.renderer.transport_url),
        ])

    def test_ssdp_alive_and_byebye_notifications_are_emitted(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.settimeout(1)
            target = listener.getsockname()
            self.tv.notify(target, alive=True)
            alive = listener.recvfrom(2048)[0].decode()
            self.tv.notify(target, alive=False)
            byebye = listener.recvfrom(2048)[0].decode()
        self.assertIn("NTS: ssdp:alive", alive)
        self.assertIn("NTS: ssdp:byebye", byebye)
        self.assertIn(self.tv.location, alive)

    def test_fake_renderer_has_a_bounded_standalone_loopback_cli(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(fake_receivers.main([
                "--profile", "strict-mime", "--duration", "0",
            ]), 0)
        self.assertIn("DLNA description: http://127.0.0.1:", output.getvalue())
        self.assertIn("SSDP test socket: 127.0.0.1:", output.getvalue())

    def test_connection_manager_query_is_read_only_and_tolerates_fault(self):
        renderer = dlna.parse_renderer(self.tv.description_xml(), self.tv.location, "127.0.0.1")
        self.assertEqual(dlna.advertised_http_formats(renderer), {"video/mp4"})
        self.tv.fail("GetProtocolInfo")
        self.assertEqual(dlna.advertised_http_formats(renderer), set())
        self.assertEqual(self.tv.calls, [("GetProtocolInfo", {}), ("GetProtocolInfo", {})])

    def test_full_transport_lifecycle_through_the_real_client(self):
        self.assertEqual(dlna.info(self.renderer)["player_state"], "IDLE")      # NO_MEDIA_PRESENT
        dlna.set_uri(self.renderer, MEDIA, "A & <B>")
        self.assertEqual(self.tv.uri, MEDIA)
        self.assertIn("A &amp; &lt;B&gt;", self.tv.metadata)                    # title escaped once
        dlna.play(self.renderer)
        self.tv.advance(30)
        status = dlna.info(self.renderer)
        self.assertEqual((status["player_state"], status["current_time"], status["duration"]),
                         ("PLAYING", 30.0, 600.0))
        dlna.pause(self.renderer)
        self.tv.advance(30)                                                      # paused: no progress
        self.assertEqual(dlna.info(self.renderer)["current_time"], 30.0)
        dlna.seek(self.renderer, 123.4)
        self.assertEqual(self.tv.position, 123.0)
        dlna.stop(self.renderer)
        self.assertEqual((self.tv.state, self.tv.position), ("STOPPED", 0.0))
        self.assertEqual([c[0] for c in self.tv.calls if c[0] in
                          ("SetAVTransportURI", "Play", "Pause", "Seek", "Stop")],
                         ["SetAVTransportURI", "Play", "Pause", "Seek", "Stop"])

    def test_rendering_control_volume_and_mute(self):
        dlna.volume(self.renderer, 55)
        dlna.set_muted(self.renderer, True)
        self.assertEqual((self.tv.volume, self.tv.muted), (55, True))
        self.assertEqual(dlna.info(self.renderer)["volume_level"], 0.55)

    def test_renderer_without_rendering_control_degrades_cleanly(self):
        with FakeDlnaRenderer(rendering_control=False) as bare:
            renderer = bare.renderer()
            self.assertEqual(renderer.rendering_url, "")
            self.assertNotIn("volume_level", dlna.info(renderer))
            with self.assertRaises(dlna.DlnaError):
                dlna.volume(renderer, 10)

    def test_end_of_media_returns_to_stopped(self):
        dlna.set_uri(self.renderer, MEDIA, "Film")
        dlna.play(self.renderer)
        self.tv.advance(10_000)
        status = dlna.info(self.renderer)
        self.assertEqual((status["player_state"], status["current_time"]), ("IDLE", 600.0))

    def test_buffering_state_before_playback(self):
        with FakeDlnaRenderer(buffer_on_play=True) as slow:
            renderer = slow.renderer()
            dlna.set_uri(renderer, MEDIA, "Film")
            dlna.play(renderer)
            self.assertEqual(dlna.info(renderer)["player_state"], "BUFFERING")
            slow.settle()
            self.assertEqual(dlna.info(renderer)["player_state"], "PLAYING")

    def test_illegal_transitions_surface_the_receivers_upnp_fault(self):
        with self.assertRaisesRegex(dlna.DlnaError, "701"):
            dlna.play(self.renderer)                      # nothing loaded
        dlna.set_uri(self.renderer, MEDIA, "Film")
        with self.assertRaisesRegex(dlna.DlnaError, "701"):
            dlna.pause(self.renderer)                     # not playing
        with self.assertRaisesRegex(dlna.DlnaError, "711"):
            dlna.seek(self.renderer, 99999)               # past the end
        self.assertEqual(self.tv.position, 0.0)

    def test_scripted_failures_are_one_shot_and_then_recover(self):
        dlna.set_uri(self.renderer, MEDIA, "Film")
        self.tv.fail("Play", http_status=500, upnp_code=501, description="Action Failed", times=2)
        for _ in range(2):
            with self.assertRaisesRegex(dlna.DlnaError, "501"):
                dlna.play(self.renderer)
        dlna.play(self.renderer)                          # third attempt succeeds
        self.assertEqual(self.tv.state, "PLAYING")
        self.assertEqual(len(self.tv.calls_of("Play")), 3)

    def test_receiver_that_hangs_up_is_reported_and_recoverable(self):
        self.tv.drop("GetTransportInfo")
        self.assertIsNone(dlna.info(self.renderer))        # info() reports "no answer"
        self.assertIsNotNone(dlna.info(self.renderer))     # next poll works

    def test_scripted_delay_slows_only_that_action(self):
        import time
        self.tv.delay("Play", 0.3)
        dlna.set_uri(self.renderer, MEDIA, "Film")
        start = time.monotonic()
        dlna.play(self.renderer)
        self.assertGreaterEqual(time.monotonic() - start, 0.3)

    def test_session_start_and_stop_drive_the_renderer(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mp4"
            movie.write_bytes(b"x" * 64)
            media = mock.Mock(path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                              width=1280, height=720, fps=25.0, duration=600.0)
            session = dlna.Session()
            session.start(media, renderer=self.renderer, local_ip="127.0.0.1", offset=0.0, title="Movie")
            try:
                self.assertTrue(session.active())
                self.assertEqual(self.tv.state, "PLAYING")
                self.assertTrue(self.tv.uri.startswith("http://127.0.0.1:"))
            finally:
                session.stop(self.renderer.key)
            self.assertEqual(self.tv.state, "STOPPED")
            self.assertFalse(session.active())

    def test_failed_play_does_not_leave_a_session_or_stop_a_foreign_film(self):
        self.tv.state, self.tv.uri = "PLAYING", "http://other/film"       # someone else's playback
        self.tv.fail("SetAVTransportURI", upnp_code=501, times=1)
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mp4"
            movie.write_bytes(b"x" * 64)
            media = mock.Mock(path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                              width=1280, height=720, fps=25.0, duration=60.0)
            session = dlna.Session()
            with self.assertRaises(dlna.DlnaError):
                session.start(media, renderer=self.renderer, local_ip="127.0.0.1", offset=0.0, title="M")
        self.assertFalse(session.active())
        self.assertEqual(self.tv.calls_of("Stop"), [])                    # ownership never began

    def test_conversion_cancel_and_disk_guard_fail_before_receiver_ownership(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mkv"
            movie.write_bytes(b"source")
            media = mock.Mock(path=movie, vcodec="hevc", acodec="eac3", pix_fmt="yuv420p",
                              width=3840, height=2160, fps=60.0, duration=60.0,
                              audio_streams=[], subtitle_tracks=[])
            cancel = threading.Event()
            cancel.set()
            session = dlna.Session()
            with self.assertRaisesRegex(dlna.DlnaError, "cancelled"):
                session.start(media, renderer=self.renderer, local_ip="127.0.0.1",
                              offset=0, title="Movie", cancel=cancel)
            with mock.patch.object(dlna.shutil, "disk_usage", return_value=mock.Mock(free=1)):
                with self.assertRaisesRegex(dlna.DlnaError, "Not enough free space"):
                    dlna.Session().start(media, renderer=self.renderer, local_ip="127.0.0.1",
                                         offset=0, title="Movie")
        self.assertEqual(self.tv.calls, [])   # preparation must not touch a playing receiver

    def test_receiver_fetches_the_real_token_url_and_ranges(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mp4"
            movie.write_bytes(bytes(range(128)))
            media = mock.Mock(path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                              width=1280, height=720, fps=25.0, duration=60.0)
            session = dlna.Session()
            session.start(media, renderer=self.renderer, local_ip="127.0.0.1", offset=0,
                          title="Movie")
            try:
                head_status, _, head_body = self.tv.fetch_media(self.tv.uri, method="HEAD")
                self.assertEqual((head_status, head_body), (200, b""))
                status, headers, body = self.tv.fetch_media(self.tv.uri, range_header="bytes=8-15")
                self.assertEqual((status, body), (206, bytes(range(8, 16))))
                self.assertEqual(headers["content-range"], "bytes 8-15/128")
                self.assertEqual(headers["accept-ranges"], "bytes")
                self.assertIn("contentfeatures.dlna.org", headers)
                self.assertEqual(self.tv.media_requests, [("HEAD", None), ("GET", "bytes=8-15")])
                wrong_token = self.tv.uri.rsplit("/", 1)[0] + "/wrong-token"
                with self.assertRaisesRegex(dlna.DlnaError, "HTTP 404"):
                    self.tv.fetch_media(wrong_token)
            finally:
                session.stop(self.renderer.key)

    def test_receiver_rejects_mismatched_content_length(self):
        response = mock.MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        response.headers.items.return_value = [
            ("Content-Type", "video/mp4"), ("Accept-Ranges", "bytes"),
            ("Content-Length", "9"),
        ]
        response.read.return_value = b"short"
        with mock.patch("fake_receivers.urlopen", return_value=response):
            with self.assertRaisesRegex(dlna.DlnaError, "mismatched Content-Length"):
                self.tv.fetch_media("http://127.0.0.1:12345/media/token")

    def test_mime_and_dlna_header_quirks_accept_smoothcast_mp4_response(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mp4"
            movie.write_bytes(b"valid test bytes")
            media = mock.Mock(path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                              width=1280, height=720, fps=25.0, duration=60.0)
            for profile in ("strict-mime", "requires-dlna-headers"):
                with self.subTest(profile=profile), FakeDlnaRenderer(profile=profile) as receiver:
                    session = dlna.Session()
                    session.start(media, renderer=receiver.renderer(), local_ip="127.0.0.1",
                                  offset=0, title="Movie")
                    try:
                        status, headers, body = receiver.fetch_media(receiver.uri)
                        self.assertEqual((status, headers["content-type"], body),
                                         (200, "video/mp4", b"valid test bytes"))
                        dlna.set_uri(receiver.renderer(), receiver.uri, "Strict MIME")
                        if profile == "strict-mime":
                            with self.assertRaisesRegex(dlna.DlnaError, "714"):
                                dlna._soap(receiver.renderer(), "SetAVTransportURI", {
                                    "InstanceID": "0", "CurrentURI": MEDIA,
                                    "CurrentURIMetaData": (
                                        '<res protocolInfo="http-get:*:video/x-matroska:*">'
                                        f"{MEDIA}</res>"),
                                })
                    finally:
                        session.stop(receiver.renderer().key)

    def test_head_refusal_and_no_range_profiles_fall_back_to_full_get(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mp4"
            movie.write_bytes(b"playable bytes")
            media = mock.Mock(path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                              width=1280, height=720, fps=25.0, duration=60.0)
            for profile in ("refuses-head", "no-range"):
                with self.subTest(profile=profile), FakeDlnaRenderer(profile=profile) as receiver:
                    session = dlna.Session()
                    session.start(media, renderer=receiver.renderer(), local_ip="127.0.0.1",
                                  offset=0, title="Movie")
                    try:
                        if profile == "refuses-head":
                            with self.assertRaisesRegex(dlna.DlnaError, "skips HEAD probes"):
                                receiver.fetch_media(receiver.uri, method="HEAD")
                        range_header = "bytes=0-1" if profile == "no-range" else None
                        status, _, body = receiver.fetch_media(receiver.uri, range_header=range_header)
                        self.assertEqual((status, body), (200, b"playable bytes"))
                        self.assertEqual(receiver.media_requests, [("GET", None)])
                    finally:
                        session.stop(receiver.renderer().key)

    def test_range_disconnect_is_reported_and_nonstandard_position_is_parsed(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "movie.mp4"
            movie.write_bytes(bytes(range(32)))
            media = mock.Mock(path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                              width=1280, height=720, fps=25.0, duration=60.0)
            with FakeDlnaRenderer(profile="closes-after-first-range") as receiver:
                session = dlna.Session()
                session.start(media, renderer=receiver.renderer(), local_ip="127.0.0.1",
                              offset=0, title="Movie")
                try:
                    self.assertEqual(receiver.fetch_media(receiver.uri, range_header="bytes=0-3")[0], 206)
                    with self.assertRaisesRegex(dlna.DlnaError, "closed the connection"):
                        receiver.fetch_media(receiver.uri, range_header="bytes=4-7")
                finally:
                    session.stop(receiver.renderer().key)
            with FakeDlnaRenderer(profile="nonstandard-position") as receiver:
                renderer = receiver.renderer()
                dlna.set_uri(renderer, MEDIA, "Film")
                dlna.play(renderer)
                receiver.advance(5)
                self.assertEqual(dlna.info(renderer)["current_time"], 5.5)


@unittest.skipUnless(os.name == "posix", "FakeCast is a POSIX shebang script")
class FakeCastTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cast = FakeCast(tmp.name)
        self.cast.__enter__()
        self.addCleanup(self.cast.__exit__)
        self.cast.add_device("Living Room")

    def test_scan_lists_online_devices_with_identity(self):
        self.cast.add_device("Kitchen", host="192.168.1.60", uuid="k-1")
        self.cast.add_device("Dead", online=False)
        names = [(d.name, d.host, d.uuid) for d in castctl.scan()]
        self.assertEqual(names, [("Kitchen", "192.168.1.60", "k-1"), ("Living Room", "192.168.1.50", "uuid-Living Room")])

    def test_control_commands_change_receiver_state_and_report_it(self):
        self.cast.update("Living Room", player_state="PLAYING", current_time=65, duration=600, title="Film")
        info = castctl.info("Living Room")
        self.assertEqual((castctl.player_state(info), info["current_time"], castctl.volume_percent(info)),
                         ("PLAYING", 65, 50))
        self.assertEqual(castctl.pause("Living Room")[0], True)
        self.assertEqual(castctl.player_state(castctl.info("Living Room")), "PAUSED")
        self.assertTrue(castctl.play("Living Room")[0])
        self.assertTrue(castctl.seek("Living Room", 119.6)[0])
        self.assertEqual(self.cast.device("Living Room")["current_time"], 120)   # rounded to whole seconds
        self.assertTrue(castctl.volume("Living Room", 80)[0])
        self.assertTrue(castctl.set_muted("Living Room", True)[0])
        device = self.cast.device("Living Room")
        self.assertEqual((device["volume_level"], device["volume_muted"]), (0.8, True))
        self.assertTrue(castctl.stop("Living Room")[0])
        self.assertEqual(castctl.player_state(castctl.info("Living Room")), "IDLE")

    def test_receiver_refusals_come_back_as_the_commands_error_text(self):
        # #461: a refusal reaches the user as one civil sentence, never the raw
        # receiver text, so the fake's wording must not leak through.
        ok, message = castctl.pause("Living Room")                     # nothing playing
        self.assertEqual((ok, message), (False, RECEIVER_FAILED))
        ok, message = castctl.seek("Living Room", 10)                  # not seekable
        self.assertEqual((ok, message), (False, RECEIVER_FAILED))
        self.assertNotIn("seekable", message)

    def test_scripted_failures_and_offline_receivers(self):
        self.cast.update("Living Room", player_state="PLAYING", duration=100)
        self.cast.fail("pause", "Failed to connect", times=1)
        self.assertEqual(castctl.pause("Living Room"), (False, RECEIVER_FAILED))
        self.assertTrue(castctl.pause("Living Room")[0])               # one-shot
        self.cast.go_offline("Living Room")
        self.assertIsNone(castctl.info("Living Room"))
        self.assertFalse(castctl.pause("Living Room")[0])
        self.assertEqual(castctl.scan(), [])

    def test_failure_can_target_one_device(self):
        self.cast.add_device("Bedroom", player_state="PLAYING")
        self.cast.update("Living Room", player_state="PLAYING")
        self.cast.fail("pause", "nope", device="Bedroom", times=5)
        self.assertTrue(castctl.pause("Living Room")[0])
        self.assertFalse(castctl.pause("Bedroom")[0])

    def test_calls_are_recorded_and_time_only_moves_when_told(self):
        self.cast.update("Living Room", player_state="PLAYING", current_time=10, duration=30)
        castctl.volume("Living Room", 20)
        castctl.pause("Living Room")
        self.assertEqual(self.cast.calls("volume"), [["volume", "20"]])
        self.assertEqual([c[0] for c in self.cast.calls()], ["volume", "pause"])
        self.cast.update("Living Room", player_state="PLAYING")
        self.cast.advance("Living Room", 15)
        self.assertEqual(self.cast.device("Living Room")["current_time"], 25)
        self.cast.advance("Living Room", 10)                           # reaches the end
        self.assertEqual(castctl.player_state(castctl.info("Living Room")), "IDLE")

    def test_direct_cast_session_end_to_end(self):
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "Film.mp4"
            movie.write_bytes(b"x")
            media = streamer.MediaInfo(path=movie, duration=600.0)
            session = streamer.Session()
            with mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer, "_save_session"):
                session.start_direct(media, device="Living Room", subs_file=None,
                                     subs_disabled=True, title="Film")
            self.assertEqual(session.mode, "direct")
            device = self.cast.device("Living Room")
            self.assertEqual((device["player_state"], device["title"], device["content_id"]),
                             ("PLAYING", "Film", str(movie)))
            self.assertIn("--no-subs", self.cast.calls("cast")[0])
            self.assertEqual(castctl.player_state(castctl.info("Living Room")), "PLAYING")

    def test_direct_cast_to_an_offline_receiver_fails_with_its_message(self):
        self.cast.go_offline("Living Room")
        with tempfile.TemporaryDirectory() as work:
            movie = Path(work) / "Film.mp4"
            movie.write_bytes(b"x")
            session = streamer.Session()
            with mock.patch.object(streamer.time, "sleep"), \
                 self.assertRaisesRegex(streamer.StreamError, "Failed to find chromecast"):
                session.start_direct(streamer.MediaInfo(path=movie, duration=60.0),
                                     device="Living Room", subs_file=None, subs_disabled=True, title="F")


@unittest.skipUnless(os.name == "posix", "FakeCast is a POSIX shebang script")
class QueueAdvanceAgainstFakeCastTests(unittest.TestCase):
    """The queue-advance protocol of cast_queue/cast_session, end to end against a fake Chromecast.

    The GUI polls the receiver and, when ``playback_ended`` says the receiver
    itself went from playing to IDLE, asks ``next_media`` for the successor and
    casts it. Here the same two decision functions and the real ``castctl`` /
    ``streamer.Session`` run against FakeCast with nothing mocked but the clock.
    """

    DEVICE = "Living Room"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cast = FakeCast(tmp.name)
        self.cast.__enter__()
        self.addCleanup(self.cast.__exit__)
        self.cast.add_device(self.DEVICE)
        folder = Path(tmp.name) / "media"
        folder.mkdir()
        names = ["Show.S01E10.mp4", "Show.S01E02.mp4", "Show.S01E01.mp4"]
        self.queue = playlist_control.natural_order([str(folder / n) for n in names])
        for item in self.queue:
            Path(item).write_bytes(b"x")
        for patcher in (mock.patch.object(streamer.time, "sleep"), mock.patch.object(streamer, "_save_session")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.session = None
        self.cast_titles: list[str] = []

    def cast_item(self, path: str) -> None:
        if self.session is not None:
            self.session.stop(self.DEVICE, send_stop=False)     # end our previous cast, as the GUI does
        media = streamer.MediaInfo(path=Path(path), duration=100.0)
        self.session = streamer.Session()
        self.session.start_direct(media, device=self.DEVICE, subs_file=None,
                                  subs_disabled=True, title=Path(path).stem)
        self.cast.update(self.DEVICE, duration=100)
        self.cast_titles.append(self.cast.device(self.DEVICE)["title"])

    def poll(self, previous: str, *, busy: bool = False) -> tuple[str, bool]:
        """One status poll: the receiver's state and whether the queue should advance."""
        state = castctl.player_state(castctl.info(self.DEVICE))
        return state, playback_state.playback_ended(
            previous, state, has_session=self.session is not None, busy=busy)

    def run_queue(self, **options) -> None:
        """Play the queue to its end the way the GUI loop does."""
        current, previous = self.queue[0], "IDLE"
        self.cast_item(current)
        for _ in range(20):                                        # bounded: a bug must not hang the test
            previous, _ended = self.poll(previous)
            self.cast.advance(self.DEVICE, 100)                    # the film plays to its end
            state, ended = self.poll(previous)
            if not ended:
                previous = state
                continue
            current = playback_state.next_media(current, self.queue, **options)
            if current is None:
                return
            self.cast_item(current)
            previous = "IDLE"

    def titles(self, *indexes: int) -> list[str]:
        return [Path(self.queue[i]).stem for i in indexes]

    def test_each_finished_item_casts_its_successor_until_the_queue_ends(self):
        self.run_queue(repeat_current=False, auto_next=True)
        self.assertEqual(self.cast_titles, self.titles(0, 1, 2))   # natural order: E01, E02, E10
        self.assertEqual(self.cast_titles[-1], "Show.S01E10")
        self.assertEqual(castctl.player_state(castctl.info(self.DEVICE)), "IDLE")
        _state, again = self.poll("IDLE")                          # the end must not re-trigger
        self.assertFalse(again)

    def test_auto_next_off_stops_after_one_item(self):
        self.run_queue(repeat_current=False, auto_next=False)
        self.assertEqual(self.cast_titles, self.titles(0))

    def test_repeat_all_wraps_and_shuffle_order_drives_the_sequence(self):
        order = playback_state.shuffle_order(self.queue, 7)
        self.assertEqual(sorted(order), sorted(self.queue))
        current = order[0]
        sequence = [current]
        for _ in range(len(order)):
            current = playback_state.next_media(current, self.queue, repeat_current=False,
                                                auto_next=True, repeat_all=True, order=order)
            sequence.append(current)
        self.assertEqual(sequence, order + [order[0]])             # visits every item, then wraps
        for item in sequence[:3]:                                  # cast the shuffled sequence for real
            self.cast_item(item)
            self.cast.advance(self.DEVICE, 100)
        self.assertEqual(self.cast_titles, [Path(i).stem for i in sequence[:3]])

    def test_the_queue_never_advances_on_anything_but_a_real_finish(self):
        self.cast_item(self.queue[0])
        state, ended = self.poll("IDLE")                           # first poll after the cast
        self.assertEqual((state, ended), ("PLAYING", False))
        castctl.pause(self.DEVICE)
        state, ended = self.poll("PLAYING")                        # paused is not finished
        self.assertEqual((state, ended), ("PAUSED", False))
        castctl.play(self.DEVICE)
        self.cast.advance(self.DEVICE, 100)                        # finished, but a command is in flight
        self.assertFalse(self.poll("PLAYING", busy=True)[1])
        self.cast.go_offline(self.DEVICE)                          # an unreachable receiver is not IDLE
        state, ended = self.poll("PLAYING")
        self.assertEqual((state, ended), ("OFFLINE", False))
        self.assertEqual(self.cast_titles, self.titles(0))

    def test_a_failed_next_cast_raises_and_leaves_nothing_playing(self):
        self.cast_item(self.queue[0])
        self.cast.advance(self.DEVICE, 100)
        self.assertTrue(self.poll("PLAYING")[1])
        self.cast.fail("cast", "Failed to connect", times=1)
        with self.assertRaises(streamer.StreamError) as caught:
            self.cast_item(playback_state.next_media(self.queue[0], self.queue,
                                                     repeat_current=False, auto_next=True))
        self.assertIn("Failed to connect", str(caught.exception))
        self.assertEqual(self.cast_titles, self.titles(0))         # no second cast was recorded
        self.assertEqual(castctl.player_state(castctl.info(self.DEVICE)), "IDLE")
        self.cast_item(self.queue[1])                              # a retry after the fault works
        self.assertEqual(self.cast_titles, self.titles(0, 1))


@unittest.skipUnless(os.name == "posix", "FakeCast is a POSIX shebang script")
class CliAgainstFakeCastTests(unittest.TestCase):
    """The headless CLI (#268) end to end: real catt subprocess protocol, no mocks."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cast = FakeCast(tmp.name)
        self.cast.__enter__()
        self.addCleanup(self.cast.__exit__)
        self.cast.add_device("Living Room", player_state="PLAYING", current_time=65, duration=600, title="Film")
        patcher = mock.patch.object(streamer, "load_session", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv: str):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_control.main([*argv, "-d", "Living Room", "--json"])
        return code, json.loads(out.getvalue())

    def test_status_pause_seek_resume_stop_round_trip(self):
        code, payload = self.run_cli("status")
        self.assertEqual((code, payload["state"], payload["position"], payload["volume"]), (0, "PLAYING", 65, 50))
        self.assertEqual(self.run_cli("pause")[0], 0)
        self.assertEqual(self.run_cli("status")[1]["state"], "PAUSED")
        self.assertEqual(self.run_cli("seek", "2:00")[0], 0)
        self.assertEqual(self.cast.device("Living Room")["current_time"], 120)
        self.assertEqual(self.run_cli("resume")[0], 0)
        self.assertEqual(self.run_cli("status")[1]["state"], "PLAYING")
        self.assertEqual(self.run_cli("stop")[0], 0)
        self.assertEqual(self.run_cli("status")[1]["state"], "IDLE")

    def test_exit_codes_follow_the_receivers_behaviour(self):
        self.cast.fail("pause", "Failed to connect")
        code, payload = self.run_cli("pause")
        self.assertEqual((code, payload["error"], payload["message"]), (1, "failed", RECEIVER_FAILED))
        self.cast.go_offline("Living Room")
        self.assertEqual(self.run_cli("status")[0], 3)                       # unreachable
        code, _ = self.run_cli("seek", "bad")
        self.assertEqual(code, 2)                                            # usage, before contact


if __name__ == "__main__":
    unittest.main()
