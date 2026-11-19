"""The auto-trim volumedetect measurement is cached (issue #235); no real ffmpeg."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer


def completed(mean: float | None) -> subprocess.CompletedProcess:
    text = "" if mean is None else f"[Parsed_volumedetect_0] mean_volume: {mean} dB\n"
    return subprocess.CompletedProcess(["ffmpeg"], 0, stdout="", stderr=text)


class VolumeCacheTests(unittest.TestCase):
    def setUp(self):
        streamer._VOLUME_CACHE.clear()
        self.addCleanup(streamer._VOLUME_CACHE.clear)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.film = Path(tmp.name) / "film.mkv"
        self.film.write_bytes(b"x" * 100)

    def measure(self, run, **kwargs):
        with mock.patch.object(streamer.subprocess, "run", run):
            return streamer.measure_mean_volume(str(self.film), **kwargs)

    def test_second_measurement_of_the_same_file_does_not_run_ffmpeg(self):
        run = mock.Mock(return_value=completed(-21.5))
        self.assertEqual(self.measure(run), -21.5)
        self.assertEqual(self.measure(run), -21.5)
        self.assertEqual(run.call_count, 1)

    def test_changed_size_or_mtime_invalidates_the_entry(self):
        run = mock.Mock(side_effect=[completed(-20.0), completed(-30.0), completed(-40.0)])
        self.assertEqual(self.measure(run), -20.0)
        self.film.write_bytes(b"x" * 101)  # size changes
        self.assertEqual(self.measure(run), -30.0)
        stamp = self.film.stat().st_mtime_ns + 5_000_000_000
        os.utime(self.film, ns=(stamp, stamp))  # only mtime changes
        self.assertEqual(self.measure(run), -40.0)
        self.assertEqual(run.call_count, 3)

    def test_track_and_window_are_part_of_the_key(self):
        run = mock.Mock(side_effect=[completed(-20.0), completed(-35.0), completed(-25.0)])
        self.assertEqual(self.measure(run, audio_track_index=0), -20.0)
        self.assertEqual(self.measure(run, audio_track_index=1), -35.0)
        self.assertEqual(self.measure(run, audio_track_index=0, max_seconds=30), -25.0)
        self.assertEqual(self.measure(run, audio_track_index=1), -35.0)  # cached
        self.assertEqual(run.call_count, 3)

    def test_failures_are_not_cached_so_a_later_attempt_can_succeed(self):
        run = mock.Mock(side_effect=[
            subprocess.TimeoutExpired("ffmpeg", 30), completed(None), completed(-22.0)])
        self.assertIsNone(self.measure(run))
        self.assertIsNone(self.measure(run))     # no audio stream / no mean line
        self.assertEqual(self.measure(run), -22.0)
        self.assertEqual(self.measure(run), -22.0)
        self.assertEqual(run.call_count, 3)

    def test_unidentifiable_file_is_never_cached(self):
        run = mock.Mock(return_value=completed(-20.0))
        with mock.patch.object(streamer.subprocess, "run", run):
            streamer.measure_mean_volume("/nonexistent/film.mkv")
            streamer.measure_mean_volume("/nonexistent/film.mkv")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(len(streamer._VOLUME_CACHE), 0)

    def test_cache_is_bounded_and_evicts_the_oldest_entry(self):
        run = mock.Mock(return_value=completed(-20.0))
        limit = streamer._VOLUME_CACHE_LIMIT
        for track in range(limit + 5):
            self.measure(run, audio_track_index=track)
        self.assertEqual(len(streamer._VOLUME_CACHE), limit)
        calls = run.call_count
        self.measure(run, audio_track_index=limit + 4)   # newest: still cached
        self.assertEqual(run.call_count, calls)
        self.measure(run, audio_track_index=0)           # oldest: evicted
        self.assertEqual(run.call_count, calls + 1)

    def test_concurrent_callers_never_corrupt_the_cache(self):
        run = mock.Mock(return_value=completed(-20.0))
        errors = []

        def worker(track):
            try:
                for _ in range(20):
                    value = streamer.measure_mean_volume(str(self.film), audio_track_index=track % 4)
                    self.assertEqual(value, -20.0)
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)
        # Patch once around all threads: mock.patch is not thread-safe, and an
        # overlapping patch/restore would leave subprocess.run mocked for
        # every later test.
        with mock.patch.object(streamer.subprocess, "run", run):
            threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10)
        self.assertEqual(errors, [])
        self.assertLessEqual(len(streamer._VOLUME_CACHE), 4)

    def test_vaapi_to_software_retry_measures_the_soundtrack_only_once(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            movie = root / "movie.mp4"
            movie.write_bytes(b"x" * 64)
            media = streamer.MediaInfo(path=movie, duration=120.0)
            session = streamer.Session()
            proc = mock.MagicMock(pid=12345)
            proc.poll.return_value = None
            volume_runs = []

            def run(args, **_kwargs):
                volume_runs.append(args)
                return completed(-24.0)
            with mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(streamer, "host_ip", return_value="192.168.1.23"), \
                 mock.patch.object(session, "_start_server"), \
                 mock.patch.object(session, "_wait_for_segments", side_effect=[False, True]), \
                 mock.patch.object(streamer, "_terminate"), \
                 mock.patch.object(streamer, "_save_session"), \
                 mock.patch.object(streamer.time, "sleep"), \
                 mock.patch.object(streamer.subprocess, "run", run), \
                 mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
                session.start_transcode(
                    media, 0.0, device="TV", device_ip="192.168.1.42", quality="balanced",
                    audio_profile="dialogue", subs_file=None, burn_subs=False, title="Film")
            self.assertTrue(session.used_software_fallback)
            self.assertEqual(popen.call_count, 3)   # VAAPI attempt, libx264 retry, catt
            self.assertEqual(len(volume_runs), 1, "retry must reuse the measurement")


if __name__ == "__main__":
    unittest.main()
