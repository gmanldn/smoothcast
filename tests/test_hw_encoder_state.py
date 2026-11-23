"""Persisted VAAPI failure so launches skip the startup stall (issue #236)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import cli
import hw_encoder_state as hw
import streamer

KEY = {"ffmpeg": "ffmpeg version 6.1", "device": "/dev/dri/renderD128",
       "driver": "i915", "kernel": "6.8.0"}


class StateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "cache" / hw.STATE_NAME

    def test_round_trip_matches_only_the_identical_key(self):
        self.assertFalse(hw.is_known_bad(self.path, KEY))          # no record yet
        self.assertTrue(hw.record_failure(self.path, KEY, now=1000.0))
        self.assertTrue(hw.is_known_bad(self.path, KEY, now=1001.0))
        for field, value in (("ffmpeg", "ffmpeg version 7.0"), ("device", "/dev/dri/renderD129"),
                             ("driver", "amdgpu"), ("kernel", "6.9.0")):
            with self.subTest(changed=field):
                self.assertFalse(hw.is_known_bad(self.path, {**KEY, field: value}, now=1001.0))

    def test_record_expires_and_future_timestamps_are_rejected(self):
        hw.record_failure(self.path, KEY, now=1000.0)
        self.assertTrue(hw.is_known_bad(self.path, KEY, now=1000.0 + hw.MAX_AGE_SECONDS))
        self.assertFalse(hw.is_known_bad(self.path, KEY, now=1000.0 + hw.MAX_AGE_SECONDS + 1))
        self.assertFalse(hw.is_known_bad(self.path, KEY, now=999.0))  # clock went backwards

    def test_corrupt_foreign_or_unreadable_records_mean_not_known_bad(self):
        self.path.parent.mkdir(parents=True)
        for text in ("{not json", "[]", "null", "{}", json.dumps({"schema": 99, "key": KEY, "failed_at": 1}),
                     json.dumps({"schema": 1, "key": KEY, "failed_at": "yesterday"}),
                     json.dumps({"schema": 1, "key": KEY})):
            with self.subTest(text=text[:30]):
                self.path.write_text(text)
                self.assertFalse(hw.is_known_bad(self.path, KEY, now=2.0))

    def test_record_is_private_atomic_and_leaves_no_temp_file(self):
        hw.record_failure(self.path, KEY)
        if os.name == "posix":                      # Windows has no POSIX permission bits
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [hw.STATE_NAME])

    def test_unwritable_location_reports_failure_without_raising(self):
        blocker = self.path.parent.parent / "file"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("x")
        self.assertFalse(hw.record_failure(blocker / "sub" / hw.STATE_NAME, KEY))

    def test_clear_removes_the_record_once(self):
        hw.record_failure(self.path, KEY)
        self.assertTrue(hw.clear(self.path))
        self.assertFalse(hw.clear(self.path))
        self.assertFalse(hw.is_known_bad(self.path, KEY))

    def test_ffmpeg_identity_changes_when_the_binary_is_replaced_and_spawns_nothing(self):
        with tempfile.TemporaryDirectory() as work:
            binary = Path(work) / "ffmpeg"
            binary.write_bytes(b"v1")
            with mock.patch.object(hw.shutil, "which", return_value=str(binary)), \
                 mock.patch("subprocess.Popen", side_effect=AssertionError("must not spawn")):
                first = hw.ffmpeg_identity()
                binary.write_bytes(b"version two")        # upgrade: new size
                second = hw.ffmpeg_identity()
        self.assertNotEqual(first, second)
        self.assertIn(str(binary.resolve()), first)

    def test_ffmpeg_identity_handles_a_missing_or_vanished_binary(self):
        with mock.patch.object(hw.shutil, "which", return_value=None):
            self.assertEqual(hw.ffmpeg_identity(), "missing")
        with mock.patch.object(hw.shutil, "which", return_value="/gone/ffmpeg"):
            self.assertEqual(hw.ffmpeg_identity(), "unknown")

    def test_driver_lookup_is_safe_without_sysfs(self):
        self.assertEqual(hw.drm_driver("/dev/dri/does-not-exist"), "")

    def test_reprobe_command_clears_the_record_and_runs_without_gtk(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            hw.record_failure(root / hw.STATE_NAME, KEY)
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(sys, "argv", ["smoothcast", "--reprobe-encoder"]):
                self.assertEqual(cli.main(), 0)
            self.assertFalse((root / hw.STATE_NAME).exists())
            self.assertNotIn("gi", sys.modules.get("cli", object()).__dict__)


class StartupBehaviourTests(unittest.TestCase):
    """Drive the real start_transcode with a mocked ffmpeg/catt, as the retry test does."""

    def run_start(self, root: Path, waits: list[bool], *, record=False):
        movie = root / "movie.mp4"
        movie.write_bytes(b"x")
        media = streamer.MediaInfo(path=movie, duration=120.0)
        session = streamer.Session()
        session.used_software_fallback = False   # as on a Linux host
        proc = mock.MagicMock(pid=4242)
        proc.poll.return_value = None
        if record:
            hw.record_failure(root / hw.STATE_NAME, KEY)
        with mock.patch.object(streamer, "ROOT", root), \
             mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
             mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
             mock.patch.object(streamer, "host_ip", return_value="192.168.1.23"), \
             mock.patch.object(hw, "current_key", return_value=KEY), \
             mock.patch.object(session, "_start_server"), \
             mock.patch.object(session, "_wait_for_segments", side_effect=waits) as wait, \
             mock.patch.object(streamer, "_terminate"), \
             mock.patch.object(streamer, "_save_session"), \
             mock.patch.object(streamer.time, "sleep"), \
             mock.patch.object(session, "_await_receiver"), \
             mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
            try:
                session.start_transcode(
                    media, 0.0, device="TV", device_ip="192.168.1.42", quality="balanced",
                    audio_profile="original", subs_file=None, burn_subs=False, title="Film")
                error = None
            except streamer.StreamError as exc:
                error = exc
        return session, popen, wait, error

    def test_known_bad_vaapi_is_skipped_so_there_is_no_15_second_stall(self):
        with tempfile.TemporaryDirectory() as work:
            session, popen, wait, error = self.run_start(Path(work), [True], record=True)
        self.assertIsNone(error)
        first = popen.call_args_list[0].args[0]
        self.assertNotIn("-hwaccel", first)
        self.assertIn("libx264", first)
        self.assertEqual([c.args[0] for c in wait.call_args_list], [30])  # never the 15 s hardware wait
        self.assertTrue(session.used_software_fallback)

    def test_first_stall_then_software_success_persists_the_failure(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            session, popen, wait, error = self.run_start(root, [False, True])
            self.assertIsNone(error)
            self.assertEqual([c.args[0] for c in wait.call_args_list], [15, 30])
            self.assertTrue(hw.is_known_bad(root / hw.STATE_NAME, KEY))
        self.assertFalse(session._vaapi_stalled)

    def test_software_failure_too_does_not_blame_the_gpu(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            session, popen, wait, error = self.run_start(root, [False, False])
            self.assertIsNotNone(error)   # the source is the problem
            self.assertFalse((root / hw.STATE_NAME).exists())

    def test_changed_environment_probes_hardware_again(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            hw.record_failure(root / hw.STATE_NAME, {**KEY, "ffmpeg": "ffmpeg version 5.0"})
            session, popen, wait, error = self.run_start(root, [True])
        self.assertIn("-hwaccel", popen.call_args_list[0].args[0])
        self.assertEqual([c.args[0] for c in wait.call_args_list], [15])

    def test_successful_hardware_start_records_nothing(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            self.run_start(root, [True])
            self.assertFalse((root / hw.STATE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
