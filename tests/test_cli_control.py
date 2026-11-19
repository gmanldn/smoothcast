"""Headless cast / pause / resume / stop / seek / status (issue #268); no GTK, no receiver."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import castctl
import cli
import cli_control as cc
import streamer

DEVICE = "Living Room"
INFO = {"player_state": "PLAYING", "current_time": 65.0, "duration": 600.0, "title": "Film",
        "volume_level": 0.4, "volume_muted": False}


def run(*argv: str, env: dict | None = None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict("os.environ", env or {}, clear=False), redirect_stdout(out), redirect_stderr(err):
        try:
            code = cc.main(list(argv))
        except SystemExit as exc:           # argparse usage errors
            code = int(exc.code)
    return code, out.getvalue(), err.getvalue()


def as_json(*argv: str, **kwargs):
    code, out, _ = run(*argv, "--json", **kwargs)
    return code, json.loads(out)


def state(**overrides) -> streamer.SessionState:
    fields = dict(file="/films/Movie.mkv", mode="transcode", offset=0.0, duration=600.0,
                  device=DEVICE, title="Movie", started_at=1.0, stream_url="http://192.168.1.2:8767/m.m3u8")
    fields.update(overrides)
    return streamer.SessionState(**fields)


class ParseTimeTests(unittest.TestCase):
    def test_accepted_forms(self):
        for text, expected in (("90", 90.0), ("90.5", 90.5), ("1:30", 90.0), ("125:30", 7530.0),
                               ("1:02:03", 3723.0), ("0", 0.0), (" 5 ", 5.0)):
            self.assertEqual(cc.parse_time(text), expected, text)

    def test_rejected_forms(self):
        for text in ("", "abc", "-5", "1:60", "1:2:60", "1:99:00", "1.5:30", "1:2:3:4", "1e3", "inf", "nan", ":", "1::2"):
            with self.subTest(text=text), self.assertRaises(cc.CliError) as caught:
                cc.parse_time(text)
            self.assertEqual(caught.exception.code, cc.EXIT_USAGE)


class DeviceTests(unittest.TestCase):
    def test_missing_device_is_a_usage_error_in_text_and_json(self):
        code, _, err = run("pause", env={cc.DEVICE_ENV: ""})
        self.assertEqual(code, cc.EXIT_USAGE)
        self.assertIn("no receiver", err)
        code, payload = as_json("pause", env={cc.DEVICE_ENV: ""})
        self.assertEqual((code, payload["ok"], payload["error"]), (cc.EXIT_USAGE, False, "usage"))

    def test_environment_variable_supplies_the_device_and_flag_wins(self):
        with mock.patch.object(castctl, "pause", return_value=(True, "")) as pause:
            self.assertEqual(run("pause", env={cc.DEVICE_ENV: "FromEnv"})[0], 0)
            pause.assert_called_with("FromEnv")
            self.assertEqual(run("pause", "-d", "FromFlag", env={cc.DEVICE_ENV: "FromEnv"})[0], 0)
            pause.assert_called_with("FromFlag")

    def test_unknown_subcommand_and_bad_flags_exit_2(self):
        for argv in (("nonsense",), ("seek",), ("cast",), ("pause", "--bogus"), ()):
            with self.subTest(argv=argv):
                self.assertEqual(run(*argv)[0], 2)


class SimpleCommandTests(unittest.TestCase):
    def test_pause_resume_success_maps_to_castctl_and_json(self):
        for command, name in (("pause", "pause"), ("resume", "play")):
            with self.subTest(command=command), \
                 mock.patch.object(castctl, name, return_value=(True, "ok")) as call, \
                 mock.patch.object(streamer, "load_session", return_value=None):
                code, payload = as_json(command, "-d", DEVICE)
                call.assert_called_once_with(DEVICE)
                self.assertEqual((code, payload["ok"], payload["command"], payload["device"]),
                                 (0, True, command, DEVICE))

    def test_failure_is_exit_1_with_the_receivers_message(self):
        with mock.patch.object(castctl, "pause", return_value=(False, "The device did not respond in time.")):
            code, payload = as_json("pause", "-d", DEVICE)
            self.assertEqual((code, payload["ok"], payload["error"]), (1, False, "failed"))
            self.assertIn("did not respond", payload["message"])
            code, out, err = run("pause", "-d", DEVICE)
            self.assertEqual((code, out), (1, ""))                  # errors go to stderr only
            self.assertIn("did not respond", err)

    def test_stop_without_our_session_just_stops_the_receiver(self):
        with mock.patch.object(streamer, "load_session", return_value=None), \
             mock.patch.object(castctl, "stop", return_value=(True, "")) as stop, \
             mock.patch.object(streamer, "Session") as session:
            code, payload = as_json("stop", "-d", DEVICE)
        stop.assert_called_once_with(DEVICE)
        session.assert_not_called()
        self.assertEqual((code, payload["ended_session"]), (0, ""))

    def test_stop_ends_our_own_cast_including_child_processes(self):
        saved = state()
        with mock.patch.object(streamer, "load_session", return_value=saved), \
             mock.patch.object(streamer, "Session") as session_class:
            code, payload = as_json("stop", "-d", DEVICE)
        instance = session_class.return_value
        instance.restore.assert_called_once_with(saved)
        instance.stop.assert_called_once_with(DEVICE, send_stop=True)
        self.assertEqual((code, payload["ended_session"]), (0, "transcode"))

    def test_a_saved_session_for_another_receiver_is_left_alone(self):
        with mock.patch.object(streamer, "load_session", return_value=state(device="Other TV")), \
             mock.patch.object(castctl, "stop", return_value=(True, "")), \
             mock.patch.object(streamer, "Session") as session_class:
            self.assertEqual(run("stop", "-d", DEVICE)[0], 0)
        session_class.assert_not_called()


class StatusTests(unittest.TestCase):
    def test_status_reports_normalised_fields(self):
        with mock.patch.object(castctl, "info", return_value=INFO), \
             mock.patch.object(streamer, "load_session", return_value=state(mode="direct")):
            code, payload = as_json("status", "-d", DEVICE)
        self.assertEqual(code, 0)
        self.assertEqual({k: payload[k] for k in ("state", "playing", "position", "duration", "volume", "muted", "seekable")},
                         {"state": "PLAYING", "playing": True, "position": 65.0, "duration": 600.0,
                          "volume": 40, "muted": False, "seekable": True})
        self.assertEqual(payload["session"]["mode"], "direct")
        self.assertEqual(payload["session"]["file"], "Movie.mkv")        # basename only

    def test_status_text_is_one_readable_line(self):
        with mock.patch.object(castctl, "info", return_value=INFO), \
             mock.patch.object(streamer, "load_session", return_value=None):
            code, out, _ = run("status", "-d", DEVICE)
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("PLAYING", out)
        self.assertIn("40%", out)

    def test_offline_receiver_is_exit_3(self):
        with mock.patch.object(castctl, "info", return_value=None):
            code, payload = as_json("status", "-d", DEVICE)
        self.assertEqual((code, payload["ok"], payload["error"]), (3, False, "unreachable"))

    def test_session_is_null_when_nothing_of_ours_is_cast(self):
        with mock.patch.object(castctl, "info", return_value=INFO), \
             mock.patch.object(streamer, "load_session", return_value=None):
            self.assertIsNone(as_json("status", "-d", DEVICE)[1]["session"])


class SeekTests(unittest.TestCase):
    def test_direct_or_foreign_playback_uses_the_receivers_seek(self):
        with mock.patch.object(streamer, "load_session", return_value=state(mode="direct")), \
             mock.patch.object(castctl, "seek", return_value=(True, "")) as seek:
            code, payload = as_json("seek", "1:30", "-d", DEVICE)
        seek.assert_called_once_with(DEVICE, 90.0)
        self.assertEqual((code, payload["position"], payload["method"]), (0, 90.0, "seek"))

    def test_receiver_refusing_the_seek_is_exit_1(self):
        with mock.patch.object(streamer, "load_session", return_value=None), \
             mock.patch.object(castctl, "seek", return_value=(False, "not seekable")):
            self.assertEqual(as_json("seek", "10", "-d", DEVICE)[0], 1)

    def test_bad_time_is_a_usage_error_before_any_receiver_contact(self):
        with mock.patch.object(castctl, "seek") as seek:
            self.assertEqual(as_json("seek", "1:99", "-d", DEVICE)[0], 2)
            self.assertEqual(as_json("seek", "-3", "-d", DEVICE)[0], 2)
        seek.assert_not_called()

    def test_live_transcode_is_restarted_at_the_new_position_with_its_settings(self):
        saved = state(quality="high", audio="night", audio_gain_db=3.0, speed=1.5, rotation=90,
                      audio_track_index=1, embedded_subtitle_index=2, burn_subs=True, title="Movie")
        media = mock.Mock(duration=600.0)
        with mock.patch.object(streamer, "load_session", return_value=saved), \
             mock.patch.object(streamer, "ffprobe", return_value=media), \
             mock.patch.object(streamer, "Session") as session_class:
            code, payload = as_json("seek", "2:00", "-d", DEVICE)
        instance = session_class.return_value
        instance.restore.assert_called_once_with(saved)
        instance.stop.assert_called_once_with(DEVICE, send_stop=False)   # no receiver Stop mid-restart
        args, kwargs = instance.start_transcode.call_args
        self.assertEqual(args, (media, 120.0))
        for key, value in (("quality", "high"), ("audio_profile", "night"), ("audio_gain_db", 3.0),
                           ("speed", 1.5), ("rotation", 90), ("audio_track_index", 1),
                           ("embedded_subtitle_index", 2), ("burn_subs", True), ("title", "Movie")):
            self.assertEqual(kwargs[key], value, key)
        self.assertEqual((code, payload["method"], payload["position"]), (0, "restart", 120.0))

    def test_restart_position_is_clamped_inside_the_film(self):
        with mock.patch.object(streamer, "load_session", return_value=state()), \
             mock.patch.object(streamer, "ffprobe", return_value=mock.Mock(duration=600.0)), \
             mock.patch.object(streamer, "Session"):
            self.assertEqual(as_json("seek", "99999", "-d", DEVICE)[1]["position"], 599.0)

    def test_restart_failures_have_the_right_codes(self):
        with mock.patch.object(streamer, "load_session", return_value=state()), \
             mock.patch.object(streamer, "ffprobe", side_effect=streamer.StreamError("bad")):
            self.assertEqual(as_json("seek", "10", "-d", DEVICE)[0], cc.EXIT_MEDIA)
        with mock.patch.object(streamer, "load_session", return_value=state()), \
             mock.patch.object(streamer, "ffprobe", return_value=mock.Mock(duration=600.0)), \
             mock.patch.object(streamer, "Session") as session_class:
            session_class.return_value.start_transcode.side_effect = streamer.StreamError("encoder died")
            code, payload = as_json("seek", "10", "-d", DEVICE)
        self.assertEqual((code, payload["error"]), (1, "failed"))


class CastTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.film = Path(tmp.name) / "Film.mkv"
        self.film.write_bytes(b"x")
        self.sub = Path(tmp.name) / "Film.srt"
        self.sub.write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n")
        self.session = mock.MagicMock()
        self.session.state = mock.Mock(stream_url="http://192.168.1.2:8767/movie-x.m3u8")
        for patcher in (mock.patch.object(streamer, "load_session", return_value=None),
                        mock.patch.object(streamer, "Session", return_value=self.session),
                        mock.patch.object(streamer, "find_subtitles", return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def probe(self, direct_ok: bool):
        return mock.patch.object(streamer, "ffprobe", return_value=mock.Mock(direct_ok=direct_ok, duration=600.0))

    def test_compatible_media_is_cast_directly(self):
        with self.probe(True):
            code, payload = as_json("cast", str(self.film), "-d", DEVICE)
        self.assertEqual((code, payload["mode"], payload["file"]), (0, "direct", "Film.mkv"))
        self.session.start_direct.assert_called_once()
        self.session.start_transcode.assert_not_called()
        self.assertEqual(self.session.start_direct.call_args.kwargs["title"], "Film")

    def test_incompatible_media_is_transcoded_with_the_chosen_options(self):
        with self.probe(False):
            code, payload = as_json("cast", str(self.film), "-d", "192.168.1.50", "--quality", "high",
                                    "--audio", "night", "--offset", "1:00", "--title", "My Film")
        self.assertEqual((code, payload["mode"], payload["offset"]), (0, "transcode", 60.0))
        args, kwargs = self.session.start_transcode.call_args
        self.assertEqual(args[1], 60.0)
        self.assertEqual((kwargs["quality"], kwargs["audio_profile"], kwargs["title"]), ("high", "night", "My Film"))
        self.assertEqual(kwargs["device_ip"], "192.168.1.50")        # literal IPv4 enables route selection
        self.assertEqual(payload["stream_url"], "http://192.168.1.2:8767/movie-x.m3u8")

    def test_mode_flag_overrides_the_automatic_choice(self):
        with self.probe(True):
            self.assertEqual(as_json("cast", str(self.film), "-d", DEVICE, "--mode", "transcode")[1]["mode"], "transcode")
        with self.probe(False):
            self.assertEqual(as_json("cast", str(self.film), "-d", DEVICE, "--mode", "direct")[1]["mode"], "direct")

    def test_device_name_is_not_mistaken_for_an_address(self):
        with self.probe(False):
            as_json("cast", str(self.film), "-d", DEVICE)
        self.assertIsNone(self.session.start_transcode.call_args.kwargs["device_ip"])

    def test_missing_or_unreadable_media_is_exit_4(self):
        code, payload = as_json("cast", "/no/such/film.mkv", "-d", DEVICE)
        self.assertEqual((code, payload["error"]), (4, "media"))
        with mock.patch.object(streamer, "ffprobe", side_effect=streamer.StreamError("No motion-video stream")):
            code, payload = as_json("cast", str(self.film), "-d", DEVICE)
        self.assertEqual((code, payload["error"]), (4, "media"))
        self.session.start_direct.assert_not_called()

    def test_start_failure_is_exit_1_and_cleans_up_without_stopping_the_receiver(self):
        self.session.start_transcode.side_effect = streamer.StreamError("the encoder failed")
        with self.probe(False):
            code, payload = as_json("cast", str(self.film), "-d", DEVICE)
        self.assertEqual((code, payload["error"]), (1, "failed"))
        self.session.stop.assert_called_once_with(DEVICE, send_stop=False)

    def test_subtitle_selection(self):
        with self.probe(True):
            as_json("cast", str(self.film), "-d", DEVICE, "--subs", str(self.sub))
            self.assertEqual(self.session.start_direct.call_args.kwargs["subs_file"], self.sub)
            as_json("cast", str(self.film), "-d", DEVICE, "--no-subs")
            kwargs = self.session.start_direct.call_args.kwargs
            self.assertEqual((kwargs["subs_file"], kwargs["subs_disabled"]), (None, True))
            code, payload = as_json("cast", str(self.film), "-d", DEVICE, "--subs", "/no/such.srt")
            self.assertEqual((code, payload["error"]), (2, "usage"))
        with self.probe(True), mock.patch.object(streamer, "find_subtitles", return_value=self.sub):
            as_json("cast", str(self.film), "-d", DEVICE)         # matching sidecar found automatically
            self.assertEqual(self.session.start_direct.call_args.kwargs["subs_file"], self.sub)

    def test_a_previous_smoothcast_cast_is_replaced_not_leaked(self):
        previous = state(device="Bedroom")
        with mock.patch.object(streamer, "load_session", return_value=previous), self.probe(True):
            self.assertEqual(as_json("cast", str(self.film), "-d", DEVICE)[0], 0)
        self.session.restore.assert_called_once_with(previous)
        self.session.stop.assert_called_with("Bedroom", send_stop=False)   # old cast's processes ended

    def test_invalid_offset_is_a_usage_error_before_probing(self):
        with mock.patch.object(streamer, "ffprobe") as probe:
            self.assertEqual(as_json("cast", str(self.film), "-d", DEVICE, "--offset", "soon")[0], 2)
        probe.assert_not_called()


class OutputContractTests(unittest.TestCase):
    def test_json_mode_prints_exactly_one_object_and_nothing_on_stderr(self):
        with mock.patch.object(castctl, "info", return_value=INFO), \
             mock.patch.object(streamer, "load_session", return_value=None):
            code, out, err = run("status", "-d", DEVICE, "--json")
        self.assertEqual(err, "")
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIsInstance(json.loads(out), dict)

    def test_help_documents_every_exit_code(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            cc.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        for needle in ("exit codes", "0 success", "1 operation failed", "2 usage", "3 receiver unreachable",
                       "4 media", "SMOOTHCAST_DEVICE", "Chromecast"):
            self.assertIn(needle, out.getvalue())


class RoutingAndIsolationTests(unittest.TestCase):
    def test_subcommands_are_routed_from_the_installed_entry_point(self):
        for command in cc.COMMANDS:
            with self.subTest(command=command), \
                 mock.patch.object(sys, "argv", ["smoothcast", command, "-d", "x"]), \
                 mock.patch.object(cc, "main", return_value=7) as handler:
                self.assertEqual(cli.main(), 7)
                handler.assert_called_once_with([command, "-d", "x"])

    def test_other_invocations_are_unchanged(self):
        with mock.patch.object(sys, "argv", ["smoothcast", "--version"]):
            self.assertEqual(cli.main(), 0)
        with mock.patch.object(sys, "argv", ["smoothcast", "movie.mkv"]), \
             mock.patch.object(cc, "main") as handler, \
             mock.patch.dict("os.environ", {"SMOOTHCAST_TEST_CONTEXT": "1"}):
            self.assertEqual(cli.main(), 2)              # still refuses to start GTK under pytest
        handler.assert_not_called()

    def test_command_paths_never_import_gtk(self):
        code = ("import sys; sys.path.insert(0, %r); import cli, cli_control; "
                "assert 'gi' not in sys.modules, sorted(m for m in sys.modules if m.startswith('gi')); "
                "assert not [m for m in sys.modules if m.startswith('cast_')], 'GUI module imported'"
                % str(ROOT / "src"))
        result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                                timeout=60, env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
