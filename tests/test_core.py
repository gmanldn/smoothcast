"""Fast, statically-embedded core regression tests.

Uses only the Python standard library (``unittest``): no GTK, no display, no
ffmpeg, no network, no third-party packages.  Imports the pure-python modules
directly so the suite runs in milliseconds on any machine.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import audio_monitor
import castctl
import server
import streamer
import version


class CastctlTests(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(castctl.fmt_time(None), "--:--")
        self.assertEqual(castctl.fmt_time(0), "00:00")
        self.assertEqual(castctl.fmt_time(5), "00:05")
        self.assertEqual(castctl.fmt_time(65), "01:05")
        self.assertEqual(castctl.fmt_time(3661), "1:01:01")
        self.assertEqual(castctl.fmt_time(-3), "00:00")

    def test_player_state(self):
        self.assertEqual(castctl.player_state(None), "OFFLINE")
        self.assertEqual(castctl.player_state({}), "OFFLINE")
        self.assertEqual(castctl.player_state({"player_state": "PLAYING"}), "PLAYING")
        self.assertEqual(castctl.player_state({"player_state": "buffering"}), "BUFFERING")
        self.assertEqual(castctl.player_state({"player_state": "paused"}), "PAUSED")

    def test_is_playing(self):
        self.assertFalse(castctl.is_playing(None))
        self.assertTrue(castctl.is_playing({"player_state": "PLAYING"}))
        self.assertTrue(castctl.is_playing({"player_state": "BUFFERING"}))
        self.assertFalse(castctl.is_playing({"player_state": "PAUSED"}))

    def test_is_seekable(self):
        self.assertFalse(castctl.is_seekable(None))
        self.assertFalse(castctl.is_seekable({}))
        self.assertFalse(castctl.is_seekable({"duration": 90}))
        self.assertFalse(castctl.is_seekable({"duration": 0, "current_time": 0}))
        self.assertTrue(castctl.is_seekable({"duration": 90, "current_time": 10}))

    def test_volume_percent(self):
        self.assertIsNone(castctl.volume_percent(None))
        self.assertIsNone(castctl.volume_percent({}))
        self.assertIsNone(castctl.volume_percent({"volume_level": "nope"}))
        self.assertEqual(castctl.volume_percent({"volume_level": 0.5}), 50)
        self.assertEqual(castctl.volume_percent({"volume_level": 1.0}), 100)
        self.assertEqual(castctl.volume_percent({"volume_level": 75}), 75)
        self.assertEqual(castctl.volume_percent({"volume_level": 200}), 100)
        self.assertEqual(castctl.volume_percent({"volume_level": -10}), 0)

    def test_volume_muted(self):
        self.assertFalse(castctl.volume_muted(None))
        self.assertFalse(castctl.volume_muted({}))
        self.assertTrue(castctl.volume_muted({"volume_muted": True}))
        self.assertFalse(castctl.volume_muted({"volume_muted": False}))


class StreamerTests(unittest.TestCase):
    def test_audio_filters_original(self):
        self.assertEqual(streamer.audio_filters("original"), [])
        self.assertEqual(streamer.audio_filters("original", 10), [])

    def test_audio_filters_profiles(self):
        dialogue = streamer.audio_filters("dialogue")
        self.assertIn("acompressor=", dialogue[0])
        self.assertIn("alimiter=", dialogue[1])
        night = streamer.audio_filters("night")
        self.assertIn("threshold=0.04", night[0])
        self.assertIn("ratio=12", night[0])
        self.assertEqual(streamer.audio_filters("unknown"), [])

    def test_audio_filters_prepends_gain(self):
        chain = streamer.audio_filters("dialogue", gain_db=6.0)
        self.assertTrue(chain[0].startswith("volume=6dB"))
        self.assertIn("acompressor=", chain[1])

    def test_effective_chain_original_skips_measurement(self):
        self.assertEqual(streamer.effective_chain("/anything.mp4", "original"), [])
        self.assertEqual(streamer.effective_chain("/anything.mp4", "original", 99), [])

    def test_effective_chain_uses_mocked_mean_volume(self):
        with mock.patch.object(streamer, "measure_mean_volume", return_value=-30.0):
            chain = streamer.effective_chain("/x.mp4", "dialogue")
        self.assertTrue(chain[0].startswith("volume=14dB"))
        self.assertIn("acompressor=", chain[1])
        self.assertIn("alimiter=", chain[-1])

    def test_atempo_filters_normal_is_identity(self):
        self.assertEqual(streamer.atempo_filters(1.0), [])
        self.assertEqual(streamer.atempo_filters(1.00), [])

    def test_atempo_filters_supported_range(self):
        self.assertEqual(streamer.atempo_filters(0.5), ["atempo=0.5"])
        self.assertEqual(streamer.atempo_filters(0.75), ["atempo=0.75"])
        self.assertEqual(streamer.atempo_filters(1.25), ["atempo=1.25"])
        self.assertEqual(streamer.atempo_filters(2.0), ["atempo=2"])

    def test_atempo_filters_chained_out_of_range(self):
        self.assertEqual(
            streamer.atempo_filters(4.0), ["atempo=2.0", "atempo=2"])
        self.assertEqual(
            streamer.atempo_filters(8.0), ["atempo=2.0", "atempo=2.0", "atempo=2"])
        self.assertEqual(
            streamer.atempo_filters(0.25), ["atempo=0.5", "atempo=0.5"])

    def test_filter_args_setpts_only(self):
        vf = streamer.Session()._filter_args(False, None, False, 1.5)
        self.assertEqual(vf, ["-vf", "setpts=PTS/1.5"])

    def test_filter_args_setpts_with_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "burned_subs.srt"
            staged.write_bytes(b"x")
            # Non-software + burned subs routes through hwdownload/hwupload.
            vf = streamer.Session()._filter_args(True, staged, False, 2.0)
        self.assertEqual(
            vf, ["-vf",
                 "hwdownload,format=nv12,subtitles=filename=burned_subs.srt,"
                 "setpts=PTS/2,hwupload"])

    def test_filter_args_software_chain(self):
        vf = streamer.Session()._filter_args(True, Path("subs.srt"), True, 0.5)
        self.assertEqual(
            vf, ["-vf", "subtitles=filename=subs.srt,setpts=PTS/0.5"])

    def test_session_state_speed_defaults_to_normal(self):
        state = streamer.SessionState(
            file="x.mp4", mode="transcode", offset=0.0, duration=100.0,
            device="TV", title="x")
        self.assertEqual(state.speed, 1.0)


    def test_direct_capable(self):
        m = streamer.MediaInfo(path=Path("movie.mp4"), vcodec="h264", acodec="aac",
                               pix_fmt="yuv420p")
        ok, reason = streamer._direct_capable(m)
        self.assertTrue(ok)
        self.assertIn("direct", reason.lower())

        m = streamer.MediaInfo(path=Path("movie.mkv"), vcodec="h264", acodec="aac")
        ok, _ = streamer._direct_capable(m)
        self.assertFalse(ok)

        m = streamer.MediaInfo(path=Path("movie.mp4"), vcodec="hevc", acodec="aac")
        ok, _ = streamer._direct_capable(m)
        self.assertFalse(ok)

        m = streamer.MediaInfo(path=Path("movie.mp4"), vcodec="h264", acodec="flac")
        ok, _ = streamer._direct_capable(m)
        self.assertFalse(ok)

    def test_find_subtitles(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "show.s01e01.mkv"
            video.write_bytes(b"x")
            (Path(tmp) / "show.s01e01.en.srt").write_bytes(b"subs")
            found = streamer.find_subtitles(video)
            self.assertIsNotNone(found)
            self.assertEqual(found.suffix, ".srt")
            self.assertEqual(streamer.find_subtitles(Path(tmp) / "nonexistent.mkv"), None)
            self.assertEqual(streamer.find_subtitles(video), found)

    def test_pid_alive(self):
        self.assertFalse(streamer.pid_alive(None))
        self.assertFalse(streamer.pid_alive(0))
        self.assertFalse(streamer.pid_alive(-5))
        # Our own process is alive.
        import os
        self.assertTrue(streamer.pid_alive(os.getpid()))
        self.assertFalse(streamer.pid_alive(999999999))

    def test_pid_alive_never_calls_os_kill_on_windows(self):
        # os.kill(pid, 0) is TerminateProcess on Windows: probing a stale PID
        # must never signal it, so the Windows path must not reach os.kill.
        from unittest import mock
        with mock.patch.object(streamer, "_IS_WINDOWS", True), \
             mock.patch.object(streamer.os, "kill") as kill:
            streamer.pid_alive(4242)
        kill.assert_not_called()

    def test_media_info_properties(self):
        m = streamer.MediaInfo(path=Path("a.mp4"), width=1920, height=1080,
                               size=1536000, bitrate=8000000)
        self.assertEqual(m.resolution, "1920x1080")
        self.assertEqual(m.size_label, "1.5 MB")
        self.assertEqual(m.bitrate_label, "8.0 Mbps")

        m = streamer.MediaInfo(path=Path("a.mp4"))
        self.assertEqual(m.resolution, "unknown")
        self.assertEqual(m.size_label, "0 B")
        self.assertEqual(m.bitrate_label, "")


class AudioMonitorTests(unittest.TestCase):
    def test_db_normal(self):
        self.assertEqual(audio_monitor._db("-20.5"), -20.5)
        self.assertEqual(audio_monitor._db(0), 0.0)
        self.assertEqual(audio_monitor._db("-60"), -60.0)

    def test_db_clamps_to_floor(self):
        self.assertEqual(audio_monitor._db("-999"), audio_monitor.FLOOR_DB)
        self.assertEqual(audio_monitor._db("-70"), audio_monitor.FLOOR_DB)

    def test_db_special_values(self):
        self.assertEqual(audio_monitor._db("nan"), audio_monitor.FLOOR_DB)
        self.assertEqual(audio_monitor._db("-inf"), audio_monitor.FLOOR_DB)
        self.assertEqual(audio_monitor._db("inf"), 0.0)
        self.assertEqual(audio_monitor._db("garbage"), audio_monitor.FLOOR_DB)
        self.assertEqual(audio_monitor._db(None), audio_monitor.FLOOR_DB)

    def test_level_sample_gain(self):
        s = audio_monitor.LevelSample(in_rms=-30, out_rms=-20, in_peak=-10,
                                      out_peak=-5, in_l=-30, in_r=-32,
                                      out_l=-20, out_r=-22)
        self.assertEqual(s.gain_db, 10.0)


class ServerTests(unittest.TestCase):
    def test_public_resource_allowed(self):
        self.assertTrue(server.public_resource("/movie.m3u8"))
        self.assertTrue(server.public_resource("/segment-00000.ts"))
        self.assertTrue(server.public_resource("/segment-99999.ts"))

    def test_public_resource_rejected(self):
        for bad in ("/", "/session.json", "/ffmpeg.log", "/burned_subs.srt",
                    "/../session.json", "/%2e%2e/session.json", "/.hidden",
                    "/movie.m3u8/extra", "/segment-.ts", "/segment.ts",
                    "/playlist.m3u8", "/movie.M3U8"):
            self.assertFalse(server.public_resource(bad), bad)


class VersionTests(unittest.TestCase):
    def test_version_format(self):
        parts = version.__version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], "1")
        self.assertEqual(parts[1], "0")
        self.assertTrue(parts[2].isdigit())


class CastctlSubprocessTests(unittest.TestCase):
    """Mocked subprocess tests for the catt command layer."""

    def _patched_run(self, returncode=0, stdout="", stderr="", exc=None):
        def fake_run(cmd, **kwargs):
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
        return mock.patch.object(castctl.subprocess, "run", side_effect=fake_run)

    def test_command_success(self):
        with self._patched_run(returncode=0, stdout="ok"):
            ok, msg = castctl.command("TV", "play")
        self.assertTrue(ok)
        self.assertEqual(msg, "ok")

    def test_command_failure_uses_stderr(self):
        with self._patched_run(returncode=1, stderr="device busy"):
            ok, msg = castctl.command("TV", "stop")
        self.assertFalse(ok)
        self.assertEqual(msg, "device busy")

    def test_command_failure_uses_stdout_when_no_stderr(self):
        with self._patched_run(returncode=1, stdout="failed"):
            ok, msg = castctl.command("TV", "pause")
        self.assertFalse(ok)
        self.assertEqual(msg, "failed")

    def test_command_timeout(self):
        with self._patched_run(exc=subprocess.TimeoutExpired("catt", 12)):
            ok, msg = castctl.command("TV", "play")
        self.assertFalse(ok)
        self.assertIn("respond in time", msg)

    def test_command_oserror(self):
        with self._patched_run(exc=OSError("no such file")):
            ok, msg = castctl.command("TV", "play")
        self.assertFalse(ok)
        self.assertEqual(msg, "no such file")

    def test_play_pause_stop_toggle(self):
        with self._patched_run(returncode=0, stdout="done"):
            self.assertEqual(castctl.play("TV"), (True, "done"))
            self.assertEqual(castctl.pause("TV"), (True, "done"))
            self.assertEqual(castctl.play_toggle("TV"), (True, "done"))
            self.assertEqual(castctl.stop("TV"), (True, "done"))

    def test_seek_clamps_and_passes_int(self):
        with self._patched_run(returncode=0, stdout="") as _m:
            castctl.seek("TV", -5)
            castctl.seek("TV", 90.7)
        calls = _m.call_args_list
        self.assertEqual(calls[0].args[0][1:], ["-d", "TV", "seek", "0"])
        self.assertEqual(calls[1].args[0][1:], ["-d", "TV", "seek", "90"])

    def test_volume_clamps(self):
        with self._patched_run(returncode=0, stdout="") as _m:
            castctl.volume("TV", -10)
            castctl.volume("TV", 150)
        self.assertEqual(_m.call_args_list[0].args[0][1:], ["-d", "TV", "volume", "0"])
        self.assertEqual(_m.call_args_list[1].args[0][1:], ["-d", "TV", "volume", "100"])

    def test_set_muted(self):
        with self._patched_run(returncode=0, stdout="") as _m:
            castctl.set_muted("TV", True)
            castctl.set_muted("TV", False)
        self.assertEqual(_m.call_args_list[0].args[0][1:], ["-d", "TV", "volumemute", "true"])
        self.assertEqual(_m.call_args_list[1].args[0][1:], ["-d", "TV", "volumemute", "false"])

    def test_subs_on_off(self):
        with self._patched_run(returncode=0, stdout="") as _m:
            castctl.subs_on("TV")
            castctl.subs_off("TV")
        self.assertEqual(_m.call_args_list[0].args[0][1:], ["-d", "TV", "subs"])
        self.assertEqual(_m.call_args_list[1].args[0][1:], ["-d", "TV", "subs", "-n"])

    def test_scan_parses_devices(self):
        json_out = '{"Living Room TV": {"host": "1.2.3.4", "port": 8009, '
        json_out += '"model_name": "Chromecast", "manufacturer": "Google", "uuid": "abc"}}'
        with self._patched_run(returncode=0, stdout=json_out):
            devices = castctl.scan()
        self.assertEqual(len(devices), 1)
        d = devices[0]
        self.assertEqual(d.name, "Living Room TV")
        self.assertEqual(d.host, "1.2.3.4")
        self.assertEqual(d.port, 8009)
        self.assertEqual(d.model, "Chromecast")

    def test_scan_bad_json_raises(self):
        with self._patched_run(returncode=0, stdout="not json"):
            with self.assertRaises(castctl.CastError):
                castctl.scan()

    def test_info_returns_none_when_offline(self):
        with self._patched_run(returncode=1):
            self.assertIsNone(castctl.info("TV"))
        with self._patched_run(exc=subprocess.TimeoutExpired("catt", 8)):
            self.assertIsNone(castctl.info("TV"))

    def test_info_returns_payload(self):
        with self._patched_run(returncode=0, stdout='{"player_state": "PLAYING"}'):
            self.assertEqual(castctl.info("TV"), {"player_state": "PLAYING"})

    def test_device_dataclass(self):
        d = castctl.Device("TV", host="1.2.3.4", port=8009)
        self.assertEqual(d.name, "TV")
        self.assertEqual(d.host, "1.2.3.4")
        self.assertEqual(d.port, 8009)
        self.assertEqual(d.model, "")
        d2 = castctl.Device("X", "", 0, "M", "Manuf", "uuid-1")
        self.assertEqual(d2.uuid, "uuid-1")


if __name__ == "__main__":
    unittest.main()
