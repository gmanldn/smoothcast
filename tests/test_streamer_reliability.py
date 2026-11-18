"""Regression tests for safe stream-server startup and stale PID handling."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer


class StreamerReliabilityTests(unittest.TestCase):
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
            ("caster", b"/usr/bin/python3\0/opt/smoothcast/.venv/bin/catt\0-d\0TV\0cast\0"),
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
