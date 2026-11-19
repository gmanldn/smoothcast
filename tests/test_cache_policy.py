"""Scratch-space cap and stale-scratch cleanup (issue #277); no GTK, no ffmpeg."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import cache_policy as cp
import config_control
import dlna
import startup_cleanup

MB = cp.MB


class CapTests(unittest.TestCase):
    def test_validation_accepts_only_bounded_integers(self):
        for good in (0, 1, 8192, cp.MAX_CAP_MB):
            self.assertEqual(cp.valid_cap_mb(good), good)
        for bad in (-1, cp.MAX_CAP_MB + 1, 1.5, "8192", None, True, [1]):
            self.assertIsNone(cp.valid_cap_mb(bad), bad)

    def test_configured_cap_reads_the_setting_and_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "config.json"
            self.assertEqual(cp.configured_cap_mb(path), cp.DEFAULT_CAP_MB)  # missing
            for text, expected in (
                (json.dumps({"cache_cap_mb": 100}), 100),
                (json.dumps({"cache_cap_mb": 0}), 0),
                (json.dumps({"cache_cap_mb": -5}), cp.DEFAULT_CAP_MB),
                (json.dumps({"cache_cap_mb": "big"}), cp.DEFAULT_CAP_MB),
                (json.dumps([1, 2]), cp.DEFAULT_CAP_MB),
                ("{not json", cp.DEFAULT_CAP_MB),
            ):
                path.write_text(text)
                self.assertEqual(cp.configured_cap_mb(path), expected, text)

    def test_reading_the_cap_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "config.json"
            path.write_text(json.dumps({"cache_cap_mb": 5}))
            cp.configured_cap_mb(path)
            self.assertEqual(sorted(p.name for p in Path(work).iterdir()), ["config.json"])

    def test_conversion_that_fits_or_has_no_cap_is_allowed(self):
        self.assertIsNone(cp.conversion_blocker(100 * MB, 200))
        self.assertIsNone(cp.conversion_blocker(200 * MB, 200))  # boundary: equal fits
        self.assertIsNone(cp.conversion_blocker(10**12, 0))      # 0 = unlimited

    def test_conversion_over_the_cap_is_refused_with_an_actionable_message(self):
        message = cp.conversion_blocker(201 * MB, 200)
        self.assertIn("201 MB", message)
        self.assertIn("cache_cap_mb", message)
        self.assertIn("Chromecast", message)

    def test_existing_scratch_counts_toward_the_cap(self):
        self.assertIsNone(cp.conversion_blocker(100 * MB, 200, in_use_bytes=100 * MB))
        self.assertIsNotNone(cp.conversion_blocker(100 * MB, 200, in_use_bytes=101 * MB))
        self.assertIsNone(cp.conversion_blocker(100 * MB, 200, in_use_bytes=-5))

    def test_directory_size_counts_files_and_ignores_symlinks(self):
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as elsewhere:
            root = Path(work)
            (root / "a").write_bytes(b"x" * 10)
            (root / "sub").mkdir()
            (root / "sub" / "b").write_bytes(b"y" * 20)
            outside = Path(elsewhere) / "big"      # a closed file: Windows cannot reopen an open one
            outside.write_bytes(b"z" * 1000)
            try:
                os.symlink(outside, root / "link")
            except (OSError, NotImplementedError):
                self.skipTest("this platform or account cannot create symlinks")
            self.assertEqual(cp.directory_size(root), 30)
            self.assertEqual(cp.directory_size(root / "missing"), 0)

    def test_setting_is_persisted_and_validated_by_the_config_loader(self):
        defaults = {"cache_cap_mb": 8192}
        self.assertEqual(config_control.sanitise_config({"cache_cap_mb": 0}, defaults)["cache_cap_mb"], 0)
        self.assertEqual(config_control.sanitise_config({"cache_cap_mb": 500}, defaults)["cache_cap_mb"], 500)
        for bad in (-1, 10**9, "x", 1.5, True):
            self.assertEqual(config_control.sanitise_config({"cache_cap_mb": bad}, defaults)["cache_cap_mb"], 8192)
        source = (ROOT / "src/cast_widgets.py").read_text("utf-8")
        self.assertIn('"cache_cap_mb": 8192', source)


class ConversionGateTests(unittest.TestCase):
    def prepare(self, size, cap_mb):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "film.mkv"
            with open(source, "wb") as handle:
                handle.truncate(size)  # sparse: reports `size` bytes, uses ~0 disk
            media = mock.Mock(path=source, audio_streams=[], subtitle_tracks=[],
                              video_stream_index=0, acodec="aac", vcodec="h264")
            with mock.patch.object(dlna.shutil, "disk_usage", return_value=mock.Mock(free=10**13)), \
                 mock.patch.object(dlna.cache_policy, "configured_cap_mb", return_value=cap_mb), \
                 mock.patch.object(dlna.cache_policy, "scratch_in_use", return_value=0), \
                 mock.patch.object(dlna.subprocess, "Popen", side_effect=AssertionError("ffmpeg must not start")):
                return dlna.prepare_mp4(media, Path(work) / "out" / "movie.mp4")

    def test_over_cap_conversion_stops_before_ffmpeg_starts(self):
        with self.assertRaisesRegex(dlna.DlnaError, "cache limit"):
            self.prepare(size=600 * MB, cap_mb=1000)  # needs ~1200 MB


@unittest.skipUnless(os.name == "posix", "POSIX scratch lease required")
class StartupSweepTests(unittest.TestCase):
    def sweep(self, scratch: Path):
        with mock.patch.object(startup_cleanup, "discover", return_value=[]), \
             mock.patch.object(startup_cleanup.streamer, "load_session", return_value=None), \
             mock.patch.object(startup_cleanup.streamer, "ROOT", scratch / "cache"):
            return startup_cleanup.cleanup_before_window(
                keep_streaming=False, proc_root=scratch / "noproc", temp_root=scratch)

    def make(self, root: Path, name: str, age: float, *, marked: bool = True):
        folder = root / name
        folder.mkdir()
        (folder / "movie.mp4").write_bytes(b"x" * 100)
        if marked and name.startswith(cp.SCRATCH_PREFIX):
            lease = cp.hold_scratch_lease(folder)
            self.assertIsNotNone(lease)
            lease.close()  # Simulates an exited/crashed owner.
        stamp = time.time() - age
        os.utime(folder, (stamp, stamp))
        return folder

    def test_old_dlna_scratch_is_removed_but_recent_and_foreign_dirs_stay(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            old = self.make(root, "smoothcast-dlna-old", cp.MIN_STALE_AGE_SECONDS + 60)
            fresh = self.make(root, "smoothcast-dlna-fresh", 5)
            foreign = self.make(root, "other-app-scratch", 10**6)
            report = self.sweep(root)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())    # may be a conversion still preparing
            self.assertTrue(foreign.exists())  # never touch unrelated directories
            self.assertEqual(report.temp_dirs_removed, 1)

    def test_old_active_conversion_survives_and_crashed_owner_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            old = self.make(
                root, "smoothcast-dlna-active", cp.MIN_STALE_AGE_SECONDS + 60,
                marked=False,
            )
            lease = cp.hold_scratch_lease(old)
            self.assertIsNotNone(lease)
            # Creating the marker updates the parent directory mtime; make
            # it old *after* the lock is held to reproduce the reported race.
            stamp = time.time() - cp.MIN_STALE_AGE_SECONDS - 60
            os.utime(old, (stamp, stamp))
            try:
                self.assertEqual((old / cp.SCRATCH_LEASE_NAME).stat().st_mode & 0o777, 0o600)
                self.assertEqual(self.sweep(root).temp_dirs_removed, 0)
                self.assertTrue((old / "movie.mp4").exists())
            finally:
                lease.close()
            self.assertEqual(self.sweep(root).temp_dirs_removed, 1)
            self.assertFalse(old.exists())

    def test_child_inherits_lease_after_parent_exits(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            old = self.make(
                root, "smoothcast-dlna-child", cp.MIN_STALE_AGE_SECONDS + 60,
                marked=False,
            )
            lease = cp.hold_scratch_lease(old)
            self.assertIsNotNone(lease)
            # Creating the marker updates the parent directory mtime; make
            # it old *after* the lock is held to reproduce the reported race.
            stamp = time.time() - cp.MIN_STALE_AGE_SECONDS - 60
            os.utime(old, (stamp, stamp))
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                pass_fds=(lease.fileno(),),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                lease.close()  # Simulate GUI crash while FFmpeg keeps writing.
                self.assertEqual(self.sweep(root).temp_dirs_removed, 0)
                self.assertTrue(old.exists())
            finally:
                proc.terminate()
                proc.wait(timeout=5)
            self.assertEqual(self.sweep(root).temp_dirs_removed, 1)
            self.assertFalse(old.exists())

    def test_legacy_or_tampered_leases_fail_closed(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            legacy = self.make(
                root, "smoothcast-dlna-legacy", cp.MIN_STALE_AGE_SECONDS + 60,
                marked=False,
            )
            linked = self.make(
                root, "smoothcast-dlna-linked", cp.MIN_STALE_AGE_SECONDS + 60,
                marked=False,
            )
            outside = root / "outside"
            outside.write_text("protected")
            (linked / cp.SCRATCH_LEASE_NAME).symlink_to(outside)
            self.assertEqual(self.sweep(root).temp_dirs_removed, 0)
            self.assertTrue(legacy.exists())
            self.assertTrue(linked.exists())
            self.assertEqual(outside.read_text(), "protected")

    def test_symlinked_scratch_is_never_followed_or_removed(self):
        with tempfile.TemporaryDirectory() as work, tempfile.TemporaryDirectory() as victim:
            root = Path(work)
            Path(victim, "precious").write_text("keep")
            os.symlink(victim, root / "smoothcast-dlna-link")
            self.sweep(root)
            self.assertTrue(Path(victim, "precious").exists())

    def test_old_generation_playlists_are_swept_with_the_other_hls_debris(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            cache = root / "cache"
            cache.mkdir()
            playlist = cache / ("movie-" + "a" * 32 + ".m3u8")
            segment = cache / ("segment-" + "a" * 32 + "-00001.ts")
            playlist.write_text("#EXTM3U")
            segment.write_bytes(b"ts")
            self.sweep(root)
            self.assertFalse(playlist.exists())
            self.assertFalse(segment.exists())


if __name__ == "__main__":
    unittest.main()
