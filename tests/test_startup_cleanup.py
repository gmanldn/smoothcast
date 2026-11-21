"""Startup orphan recovery: preserve casts and never kill unrelated PIDs.

This suite deliberately mocks all kill operations. No subprocesses, GTK or
Chromecast devices are required.
"""
from pathlib import Path
import os
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import startup_cleanup as cleanup
import streamer


def process(pid, kind):
    argv = {
        "server": ("python3", str(streamer.SERVER_SCRIPT)),
        "encoder": ("ffmpeg", "-progress", str(streamer.PROGRESS_FILE)),
        "monitor": (
            "ffmpeg", "-filter_complex",
            "ametadata=mode=print:file=/tmp/cast-mon-xyz/in.txt",
        ),
        "local": ("ffplay", "-window_title", "SmoothCast — local playback"),
    }
    return cleanup.Process(pid, kind, 100, argv[kind])


class StartupCleanupTests(unittest.TestCase):
    def test_only_project_owned_command_signatures_match(self):
        self.assertIsNone(cleanup.process_kind(("ffmpeg", "-i", "other.mp4")))
        self.assertIsNone(cleanup.process_kind(("catt", "-d", "TV", "cast", "https://x")))
        self.assertIsNone(cleanup.process_kind(("python3", "-c", "print(1)", str(streamer.SERVER_SCRIPT))))
        self.assertIsNone(cleanup.process_kind(("ffplay", "-i", "video.mp4")))
        for kind in ("server", "encoder", "monitor", "local"):
            self.assertEqual(cleanup.process_kind(process(100, kind).argv), kind)

    def test_existing_kept_hls_stream_survives_relaunch(self):
        with TemporaryDirectory() as d:
            processes = [process(100, "server"), process(101, "encoder"),
                         process(102, "monitor")]
            state = streamer.SessionState(
                file="/x", mode="transcode", offset=0, duration=10,
                device="TV", title="Film", server_pid=100, ffmpeg_pid=101,
            )
            with mock.patch.object(cleanup, "discover", return_value=processes), \
                 mock.patch.object(streamer, "load_session", return_value=state), \
                 mock.patch.object(cleanup, "_stop_orphans") as stop:
                report = cleanup.cleanup_before_window(
                    keep_streaming=True, temp_root=Path(d),
                )
            self.assertTrue(report.retained_stream)
            self.assertEqual(report.preserved, [100, 101])
            self.assertEqual([p.pid for p in stop.call_args.args[0]], [102])

    def test_retained_hls_stream_keeps_its_final_segments(self):
        # A kept HLS cast is still draining on the receiver; its final
        # playlist and segments must survive cleanup or the receiver would
        # start 404ing ranges mid-film.
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "segment-00000.ts").write_text("segment")
            (root / "segment-00001.ts").write_text("segment")
            (root / "movie.m3u8").write_text(
                "#EXTM3U\n#EXTINF:2,\nsegment-00001.ts\n#EXT-X-ENDLIST\n")
            processes = [process(100, "server"), process(101, "encoder")]
            state = streamer.SessionState(
                file="/x", mode="transcode", offset=0, duration=10,
                device="TV", title="Film", server_pid=100, ffmpeg_pid=101,
            )
            with mock.patch.object(cleanup, "discover", return_value=processes), \
                 mock.patch.object(streamer, "load_session", return_value=state), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(cleanup, "_stop_orphans"):
                report = cleanup.cleanup_before_window(
                    keep_streaming=True, temp_root=root,
                )
            self.assertTrue(report.retained_stream)
            self.assertEqual(report.files_removed, 0)
            self.assertTrue((root / "segment-00000.ts").exists())
            self.assertTrue((root / "segment-00001.ts").exists())
            self.assertTrue((root / "movie.m3u8").exists())

    def test_reused_server_without_saved_pid_is_preserved(self):
        with TemporaryDirectory() as d:
            processes = [process(100, "server"), process(101, "encoder")]
            state = streamer.SessionState(
                file="/x", mode="transcode", offset=0, duration=10,
                device="TV", title="Film", ffmpeg_pid=101,
            )
            with mock.patch.object(cleanup, "discover", return_value=processes), \
                 mock.patch.object(streamer, "load_session", return_value=state), \
                 mock.patch.object(cleanup, "_stop_orphans") as stop:
                report = cleanup.cleanup_before_window(
                    keep_streaming=True, temp_root=Path(d),
                )
            self.assertEqual(report.preserved, [100, 101])
            self.assertEqual(stop.call_args.args[0], [])

    def test_orphans_and_hls_files_are_cleaned_without_touching_logs(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "segment-00001.ts").write_text("segment")
            (root / "movie.m3u8").write_text("playlist")
            (root / "ffmpeg.log").write_text("keep logs")
            processes = [process(100, "server"), process(102, "monitor")]
            with mock.patch.object(cleanup, "discover", return_value=processes), \
                 mock.patch.object(streamer, "load_session", return_value=None), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "SESSION_FILE", root / "session.json"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
                 mock.patch.object(cleanup, "_stop_orphans") as stop:
                report = cleanup.cleanup_before_window(
                    keep_streaming=True, temp_root=root,
                )
            self.assertFalse(report.retained_stream)
            self.assertEqual([p.pid for p in stop.call_args.args[0]], [100, 102])
            self.assertEqual(report.files_removed, 2)
            self.assertTrue((root / "ffmpeg.log").exists())

    def test_abandoned_staged_captions_cleaned_but_saved_direct_captions_kept(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            captions = [root / "receiver_subs.srt", root / "burned_subs.srt"]
            for path in captions:
                path.write_bytes(b"staged")
            (root / "ffmpeg.log").write_text("diagnostics preserved")
            with mock.patch.object(cleanup, "discover", return_value=[]), \
                 mock.patch.object(streamer, "load_session", return_value=None), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "SESSION_FILE", root / "session.json"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"):
                result = cleanup.cleanup_before_window(
                    keep_streaming=False, temp_root=root,
                )
            self.assertEqual(result.files_removed, 2)
            self.assertTrue(all(not path.exists() for path in captions))
            self.assertTrue((root / "ffmpeg.log").exists())

            (root / "receiver_subs.srt").write_bytes(b"still in use")
            saved = streamer.SessionState(
                file="/elsewhere/movie.mp4", mode="direct", offset=0,
                duration=5, device="TV", title="A film",
            )
            with mock.patch.object(cleanup, "discover", return_value=[]), \
                 mock.patch.object(streamer, "load_session", return_value=saved), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "SESSION_FILE", root / "session.json"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"):
                result = cleanup.cleanup_before_window(
                    keep_streaming=True, temp_root=root,
                )
            self.assertTrue(result.retained_stream)
            self.assertEqual((root / "receiver_subs.srt").read_bytes(), b"still in use")

    def test_disabled_keep_streaming_discards_saved_session(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "session.json").write_text("state")
            state = streamer.SessionState(
                file="/x", mode="transcode", offset=0, duration=10,
                device="TV", title="Film", server_pid=100, ffmpeg_pid=101,
            )
            with mock.patch.object(cleanup, "discover", return_value=[
                    process(100, "server"), process(101, "encoder")]), \
                 mock.patch.object(streamer, "load_session", return_value=state), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "SESSION_FILE", root / "session.json"), \
                 mock.patch.object(cleanup, "_stop_orphans") as stop:
                report = cleanup.cleanup_before_window(
                    keep_streaming=False, temp_root=root,
                )
            self.assertFalse(report.retained_stream)
            self.assertEqual([p.pid for p in stop.call_args.args[0]], [100, 101])
            self.assertFalse((root / "session.json").exists())

    def test_direct_stream_state_is_preserved_for_device_validation(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "session.json").write_text("keep me")
            (root / "movie.m3u8").write_text("old stream")
            (root / "segment-00001.ts").write_text("old segment")
            state = streamer.SessionState(
                file="/x", mode="direct", offset=0, duration=10,
                device="TV", title="Film",
            )
            with mock.patch.object(cleanup, "discover", return_value=[]), \
                 mock.patch.object(streamer, "load_session", return_value=state), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "SESSION_FILE", root / "session.json"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"):
                report = cleanup.cleanup_before_window(
                    keep_streaming=True, temp_root=root,
                )
            self.assertTrue(report.retained_stream)
            self.assertTrue((root / "session.json").exists())
            self.assertFalse((root / "movie.m3u8").exists())
            self.assertFalse((root / "segment-00001.ts").exists())
            self.assertEqual(report.files_removed, 2)

    def test_pid_reuse_never_receives_a_signal(self):
        p = process(100, "server")
        newer = cleanup.Process(100, p.kind, p.start_ticks + 1, p.argv)
        with mock.patch.object(cleanup, "inspect_process", return_value=newer), \
             mock.patch.object(cleanup.os, "kill") as kill:
            cleanup._stop_orphans(
                [p], Path("/proc"), cleanup.CleanupReport(), 0,
            )
            kill.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX /proc process identity and signals")
    def test_verified_stale_process_gets_bounded_sigterm_and_sigkill(self):
        proc = process(100, "encoder")
        report = cleanup.CleanupReport()
        with mock.patch.object(cleanup.platform, "system", return_value="Darwin"), \
             mock.patch.object(cleanup, "_same_process", return_value=True), \
             mock.patch.object(cleanup.process_identity, "signal_verified", return_value=True) as signal:
            cleanup._stop_orphans([proc], Path("/proc"), report, 0.0)
        self.assertEqual(report.stopped, [100])
        self.assertEqual(
            [call.kwargs["force"] for call in signal.call_args_list],
            [False, True],
        )

    @unittest.skipIf(os.name == "nt", "POSIX user-id process ownership")
    def test_other_users_processes_are_never_inspected_or_signalled(self):
        with TemporaryDirectory() as d:
            pid = 55001
            folder = Path(d) / str(pid)
            folder.mkdir()
            (folder / "cmdline").write_bytes(
                b"ffmpeg\0-progress\0" + str(streamer.PROGRESS_FILE).encode() + b"\0"
            )
            (folder / "stat").write_text("irrelevant")
            with mock.patch.object(cleanup.os, "getuid", return_value=-1):
                self.assertIsNone(cleanup.inspect_process(pid, Path(d)))

    @unittest.skipIf(os.name == "nt", "Linux /proc process start-time parser")
    def test_proc_starttime_with_parentheses_in_command_name(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            pid = 54721
            location = root / str(pid)
            location.mkdir()
            (location / "cmdline").write_bytes(
                b"ffmpeg\0-progress\0" + str(streamer.PROGRESS_FILE).encode()
                + b"\0"
            )
            fields = ["S"] + ["0"] * 18 + ["7319"] + ["0"] * 3
            (location / "stat").write_text(
                f"{pid} (ffmpeg (worker)) " + " ".join(fields)
            )
            found = cleanup.inspect_process(pid, root)
            self.assertIsNotNone(found)
            self.assertEqual(found.start_ticks, 7319)
            self.assertEqual(found.kind, "encoder")

    @unittest.skipIf(os.name == "nt", "POSIX user-id process ownership")
    def test_only_owned_orphan_meter_directories_are_removed(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            old = root / "cast-mon-old"
            old.mkdir()
            (old / "in.txt").write_text("x")
            fresh = root / "cast-mon-new"
            fresh.mkdir()
            unrelated = root / "unrelated"
            unrelated.mkdir()
            os.utime(old, (1, 1))
            with mock.patch.object(cleanup, "discover", return_value=[]), \
                 mock.patch.object(streamer, "load_session", return_value=None), \
                 mock.patch.object(streamer, "ROOT", root), \
                 mock.patch.object(streamer, "SESSION_FILE", root / "session.json"), \
                 mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"):
                report = cleanup.cleanup_before_window(
                    keep_streaming=False, temp_root=root,
                )
            self.assertEqual(report.temp_dirs_removed, 2)
            self.assertFalse(old.exists())
            self.assertFalse(fresh.exists())
            self.assertTrue(unrelated.exists())

    def test_primary_only_startup_wiring_and_selftest_exclusion(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "cast_control.py").read_text()
        startup = source.split("    def do_startup(self)", 1)[1].split(
            "    def _register_actions(self)", 1
        )[0]
        self.assertIn("if not self.selftest:", startup)
        self.assertIn("startup_cleanup.cleanup_before_window(", startup)
        self.assertIn('keep_streaming=bool(load_config().get("keep_streaming", True))', startup)
        self.assertIn("self._startup_reported = True", source)


if __name__ == "__main__":
    unittest.main()
