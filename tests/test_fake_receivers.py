"""Production code against the fake receivers (issue #278): no mocks of dlna/castctl."""
from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import castctl
import cli_control
import dlna
import streamer
from fake_receivers import FakeCast, FakeDlnaRenderer, allow_loopback

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

    def test_discovery_description_parses_to_the_same_endpoints(self):
        import urllib.request
        body = urllib.request.urlopen(self.tv.location, timeout=3).read()
        parsed = dlna.parse_renderer(body, self.tv.location, "127.0.0.1")
        self.assertEqual((parsed.name, parsed.model), ("Fake TV", "FakeDMR"))
        self.assertEqual(parsed.transport_url, self.renderer.transport_url)
        self.assertEqual(parsed.rendering_url, self.renderer.rendering_url)

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
        ok, message = castctl.pause("Living Room")                     # nothing playing
        self.assertEqual((ok, message), (False, "Nothing is playing."))
        ok, message = castctl.seek("Living Room", 10)                  # not seekable
        self.assertFalse(ok)
        self.assertIn("not seekable", message)

    def test_scripted_failures_and_offline_receivers(self):
        self.cast.update("Living Room", player_state="PLAYING", duration=100)
        self.cast.fail("pause", "Failed to connect", times=1)
        self.assertEqual(castctl.pause("Living Room"), (False, "Failed to connect"))
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
        self.assertEqual((code, payload["error"], payload["message"]), (1, "failed", "Failed to connect"))
        self.cast.go_offline("Living Room")
        self.assertEqual(self.run_cli("status")[0], 3)                       # unreachable
        code, _ = self.run_cli("seek", "bad")
        self.assertEqual(code, 2)                                            # usage, before contact


if __name__ == "__main__":
    unittest.main()
