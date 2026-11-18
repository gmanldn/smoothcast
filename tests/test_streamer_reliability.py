"""Regression tests for safe stream-server startup and stale PID handling."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer


class StreamerReliabilityTests(unittest.TestCase):
    def test_stalled_vaapi_encoder_falls_back_even_if_process_is_alive(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = Path(work)
            media = streamer.MediaInfo(path=root / "movie.mp4", duration=120.0)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.pid = 12345
            proc.poll.return_value = None  # Hardware encoder hangs, never exits.
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.23"), \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", side_effect=[False, True]) as wait, \
                 mock.patch.object(streamer, "_terminate") as terminate, \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 45.0, device="TV", device_ip="192.168.1.42",
                    quality="balanced", audio_profile="original",
                    subs_file=None, burn_subs=False, title="Film",
                    speed=1.5, rotation=90,
                )
            self.assertTrue(session.used_software_fallback)
            self.assertEqual([call.args[0] for call in wait.call_args_list], [15, 30])
            terminate.assert_called_once_with(proc)
            self.assertEqual(popen.call_count, 3)  # VAAPI, libx264, catt.
            first_args, second_args = (call.args[0] for call in popen.call_args_list[:2])
            self.assertIn("-hwaccel", first_args)
            self.assertNotIn("-hwaccel", second_args)
            self.assertIn("libx264", second_args)
            # Fallback is not allowed to silently revert user's transforms.
            self.assertIn("-readrate", second_args)
            self.assertEqual(second_args[second_args.index("-readrate") + 1], "1.5")
            self.assertIn("setpts=PTS/1.5", ",".join(second_args))
            self.assertIn("transpose=1", ",".join(second_args))
            self.assertIn("atempo=1.5", ",".join(second_args))
            self.assertEqual(session.state.speed, 1.5)
            self.assertEqual(session.state.rotation, 90)
            self.assertIn("192.168.1.23:8767", session.state.stream_url)

    def test_direct_cast_remains_active_after_successful_catt_exit(self):
        session = streamer.Session()
        session.state = streamer.SessionState(
            file="movie.mp4", mode="direct", offset=0.0, duration=120,
            device="TV", title="Film",
        )
        caster = mock.Mock()
        caster.poll.return_value = 0  # catt exits on success, Chromecast keeps playing.
        session.caster = caster
        self.assertTrue(session.active())
        session.state = None
        self.assertFalse(session.active())

    def test_direct_start_records_original_audio_for_transcode_resume(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = Path(work)
            media = streamer.MediaInfo(path=root / "movie.mp4", duration=90.0)
            session = streamer.Session()
            proc = mock.MagicMock()
            proc.poll.return_value = 0  # catt successfully sent the cast.
            proc.returncode = 0
            with mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc):
                session.start_direct(
                    media, device="TV", title="Film", subs_file=None,
                    subs_disabled=True,
                )
            self.assertEqual(session.state.audio, "original")

    def test_direct_resume_seeks_tv_and_records_real_offset(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            media = streamer.MediaInfo(path=Path(work) / "movie.mp4", duration=90.0)
            session = streamer.Session()
            caster = mock.MagicMock()
            caster.poll.return_value = 0
            caster.returncode = 0
            with mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=caster), \
                 mock.patch.object(streamer.castctl, "seek", return_value=(True, "")) as seek:
                session.start_direct(
                    media, device="TV", title="Film", subs_file=None,
                    subs_disabled=True, offset=51.25,
                )
            seek.assert_called_once_with("TV", 51.25)
            self.assertEqual(session.state.offset, 51.25)

    def test_failed_direct_resume_can_fall_back_to_transcoder(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            media = streamer.MediaInfo(path=Path(work) / "movie.mp4", duration=90.0)
            session = streamer.Session()
            caster = mock.MagicMock()
            caster.poll.return_value = 0
            caster.returncode = 0
            with mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=caster), \
                 mock.patch.object(streamer.castctl, "seek", return_value=(False, "Not seekable")):
                with self.assertRaisesRegex(streamer.StreamError, "Direct resume seek failed"):
                    session.start_direct(
                        media, device="TV", title="Film", subs_file=None,
                        subs_disabled=True, offset=51.25,
                    )
            self.assertIsNone(session.state)  # caller may recover using HLS.

    def test_cast_route_preferred_over_other_interfaces(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.getsockname.return_value = ("192.168.1.23", 54000)
        with mock.patch.object(streamer.socket, "socket", return_value=fake):
            self.assertEqual(streamer.host_ip("192.168.1.42"), "192.168.1.23")
        fake.connect.assert_called_once_with(("192.168.1.42", 8009))

    def test_host_ip_skips_unusable_addresses(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.getsockname.return_value = ("127.0.0.1", 54000)
        with mock.patch.object(streamer.socket, "socket", return_value=fake), \
             mock.patch.object(streamer.subprocess, "check_output", return_value="127.0.0.1 169.254.1.1 192.168.5.3"):
            self.assertEqual(streamer.host_ip(), "192.168.5.3")

    def test_no_lan_ip_gives_a_clear_error(self):
        with mock.patch.object(streamer.socket, "socket", side_effect=OSError("no route")), \
             mock.patch.object(streamer.subprocess, "check_output", side_effect=OSError("no interfaces")):
            with self.assertRaisesRegex(streamer.StreamError, "LAN IPv4"):
                streamer.host_ip("192.168.1.42")

    def test_an_unrelated_port_owner_is_not_reused(self):
        session = streamer.Session()
        with mock.patch.object(streamer, "_port_open", return_value=True), \
             mock.patch.object(streamer, "_server_healthy", return_value=False), \
             mock.patch.object(streamer.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(streamer.StreamError, "occupied"):
                session._start_server()
            popen.assert_not_called()

    def test_existing_healthy_server_is_reused(self):
        session = streamer.Session()
        with mock.patch.object(streamer, "_port_open", return_value=True), \
             mock.patch.object(streamer, "_server_healthy", return_value=True), \
             mock.patch.object(streamer.subprocess, "Popen") as popen:
            session._start_server()
            popen.assert_not_called()
            self.assertIsNone(session.server)

    def test_failed_server_process_is_detected_immediately(self):
        session = streamer.Session()
        with mock.patch.object(streamer, "_port_open", return_value=False), \
             mock.patch.object(streamer, "_server_healthy", return_value=False), \
             mock.patch.object(streamer.subprocess, "Popen") as popen:
            popen.return_value.poll.return_value = 1
            with self.assertRaisesRegex(streamer.StreamError, "exited"):
                session._start_server()

    def test_reused_pid_is_never_killed(self):
        with mock.patch.object(streamer, "pid_alive", return_value=True), \
             mock.patch.object(Path, "read_bytes", return_value=b"/usr/bin/firefox\0--new-window\0"), \
             mock.patch.object(streamer.os, "kill") as kill:
            for role in ("server", "encoder", "caster"):
                self.assertFalse(streamer._pid_is_ours(12345, role))
                streamer._terminate_pid(12345, role)
            kill.assert_not_called()

    def test_only_expected_process_command_lines_can_be_restored(self):
        cases = (
            ("server", f"/usr/bin/python3\0{streamer.SERVER_SCRIPT}\0".encode()),
            ("encoder", f"ffmpeg\0-progress\0{streamer.PROGRESS_FILE}\0".encode()),
            ("caster", b"/usr/bin/python3\0/usr/local/bin/catt\0-d\0TV\0cast\0"),
        )
        with mock.patch.object(streamer, "pid_alive", return_value=True):
            for role, command in cases:
                with self.subTest(role=role), mock.patch.object(Path, "read_bytes", return_value=command):
                    self.assertTrue(streamer._pid_is_ours(12345, role))
                    self.assertFalse(streamer._pid_is_ours(12345, "unknown"))

    def test_stale_session_pids_are_not_adopted(self):
        state = streamer.SessionState(
            file="/tmp/missing.mp4", mode="transcode", offset=0, duration=90,
            device="TV", title="Missing", ffmpeg_pid=123, server_pid=124, caster_pid=125,
        )
        session = streamer.Session()
        with mock.patch.object(streamer, "_pid_is_ours", return_value=False):
            session.restore(state)
            self.assertFalse(session.active())
            self.assertIsNone(session.ffmpeg)
            self.assertIsNone(session.server)
            self.assertIsNone(session.caster)


if __name__ == "__main__":
    unittest.main()


class OneSegmentHlsTests(unittest.TestCase):
    """A very short clip can finalise with one complete HLS segment."""

    def _session(self, root, returncode):
        session = streamer.Session()
        proc = mock.MagicMock()
        proc.poll.return_value = returncode
        proc.returncode = returncode
        session.ffmpeg = proc
        return session

    def test_finalised_single_segment_playlist_is_accepted(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = Path(work)
            (root / "segment-00000.ts").write_bytes(b"TS")
            (root / "movie.m3u8").write_text(
                "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2.0,\n"
                "segment-00000.ts\n#EXT-X-ENDLIST\n",
                encoding="utf-8",
            )
            session = self._session(root, 0)
            with mock.patch.object(streamer, "ROOT", root):
                self.assertTrue(session._wait_for_segments(1.0))

    def test_single_segment_playlist_with_missing_segment_is_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = Path(work)
            (root / "movie.m3u8").write_text(
                "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2.0,\n"
                "segment-00000.ts\n#EXT-X-ENDLIST\n",
                encoding="utf-8",
            )
            session = self._session(root, 0)
            with mock.patch.object(streamer, "ROOT", root):
                self.assertFalse(session._wait_for_segments(0.5))

    def test_failed_encode_does_not_accept_a_single_segment(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = Path(work)
            (root / "segment-00000.ts").write_bytes(b"TS")
            (root / "movie.m3u8").write_text(
                "#EXTM3U\n#EXTINF:2.0,\nsegment-00000.ts\n#EXT-X-ENDLIST\n",
                encoding="utf-8",
            )
            session = self._session(root, 1)
            with mock.patch.object(streamer, "ROOT", root):
                self.assertFalse(session._wait_for_segments(0.5))

    def test_unfinalised_playlist_after_exit_is_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as work:
            root = Path(work)
            (root / "segment-00000.ts").write_bytes(b"TS")
            (root / "movie.m3u8").write_text(
                "#EXTM3U\n#EXTINF:2.0,\nsegment-00000.ts\n",
                encoding="utf-8",
            )
            session = self._session(root, 0)
            with mock.patch.object(streamer, "ROOT", root):
                self.assertFalse(session._wait_for_segments(0.5))


class ProgressSamplerTests(unittest.TestCase):
    """SC-069 #78: GTK callbacks read a snapshot sampled off the GTK thread."""

    def test_progress_and_segment_count_are_cache_only(self):
        session = streamer.Session()
        session._progress_snapshot = {"speed": "1.5x", "out_time": 4.0}
        session._segments_snapshot = 7
        with mock.patch.object(
                streamer.Session, "_read_progress",
                side_effect=AssertionError("must not read disk")), \
             mock.patch.object(streamer, "ROOT") as root:
            self.assertEqual(session.progress()["speed"], "1.5x")
            self.assertEqual(session.segment_count(), 7)
            root.glob.assert_not_called()

    def test_sampler_primes_the_snapshot_and_stops_cleanly(self):
        session = streamer.Session()
        with mock.patch.object(session, "_read_progress",
                               return_value={"speed": "2x"}), \
             mock.patch.object(session, "_count_segments", return_value=3):
            session._start_sampler()
            self.assertEqual(session.progress(), {"speed": "2x"})
            self.assertEqual(session.segment_count(), 3)
            session._stop_sampler()
        self.assertIsNone(session._sampler)
