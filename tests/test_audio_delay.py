"""Per-film audio delay / lip-sync (issue #113): maths, config, FFmpeg arguments, DLNA, live adjust.

No GTK, no receiver. Real-FFmpeg timing measurements are in test_audio_delay_ffmpeg.py.
"""
from __future__ import annotations

from pathlib import Path
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import audio_delay as ad
import config_control
import dlna
import streamer
from test_restart_settings import run_restart, state, window


# --- pure maths ------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (0, 0), (300, 300), (-300, -300), (5000, 5000), (5001, 5000), (-9999, -5000),
    (49.6, 50), (-49.6, -50), (float("nan"), 0), (float("inf"), 0), (True, 0),
    (None, 0), ("300", 0), ([], 0),
])
def test_normalize_is_whole_milliseconds_clamped_and_safe(raw, expected):
    assert ad.normalize(raw) == expected


def test_step_moves_50_ms_and_stops_at_the_limits():
    assert ad.step(0, 1) == 50 and ad.step(0, -1) == -50 and ad.step(120, 0) == 120
    assert ad.step(4980, 1) == 5000 and ad.step(5000, 1) == 5000
    assert ad.step(-4980, -1) == -5000 and ad.step("junk", 1) == 50


def test_labels_are_short_and_signed():
    assert ad.label(0) == "Off" and ad.label("x") == "Off"
    assert ad.label(150) == "+0.15 s" and ad.label(1500) == "+1.5 s"
    assert ad.label(-300) == "−0.3 s" and ad.label(-5000) == "−5 s"


def test_positive_delay_pads_silence_negative_trims_and_zero_adds_nothing():
    assert ad.filters(300) == ["adelay=delays=300:all=1"]
    assert ad.filters(-300) == ["atrim=start=0.300", "asetpts=PTS-STARTPTS"]
    assert ad.filters(-1250) == ["atrim=start=1.250", "asetpts=PTS-STARTPTS"]
    assert ad.filters(0) == [] and ad.filters(None) == [] and ad.filters(float("nan")) == []
    assert ad.filters(10**9) == ["adelay=delays=5000:all=1"]               # clamped


def test_get_and_put_are_per_film_bounded_and_clear_at_zero():
    cfg: dict = {}
    assert ad.get(cfg, "/m/a.mkv") == 0 and ad.get(None, "/m/a.mkv") == 0
    assert ad.put(cfg, "/m/a.mkv", 150) == 150 and ad.get(cfg, "/m/a.mkv") == 150
    assert ad.get(cfg, "/m/b.mkv") == 0                                      # another film is unaffected
    ad.put(cfg, "/m/a.mkv", 0)
    assert ad.CONFIG_KEY not in cfg or "/m/a.mkv" not in cfg[ad.CONFIG_KEY]
    cfg = {ad.CONFIG_KEY: "garbage"}
    assert ad.get(cfg, "/m/a.mkv") == 0 and ad.put(cfg, "/m/a.mkv", 50) == 50
    for i in range(ad.MAX_ENTRIES + 20):
        ad.put(cfg, f"/m/{i}.mkv", 50)
    assert len(cfg[ad.CONFIG_KEY]) == ad.MAX_ENTRIES and ad.get(cfg, f"/m/{ad.MAX_ENTRIES + 19}.mkv") == 50


def test_config_loader_keeps_only_sane_per_film_delays():
    raw = {"audio_delay_by_file": {"/a.mkv": 300, "/b.mkv": -5000, "/c.mkv": 5001, "/d.mkv": 0,
                                   "/e.mkv": 1.5, "/f.mkv": "9", "": 100, 7: 100, "/g.mkv": True}}
    out = config_control.sanitise_config(raw, {"audio_delay_by_file": {}})["audio_delay_by_file"]
    assert out == {"/a.mkv": 300, "/b.mkv": -5000}
    for junk in ([], "x", None, 5):
        assert config_control.sanitise_config({"audio_delay_by_file": junk},
                                              {"audio_delay_by_file": {}})["audio_delay_by_file"] == {}


# --- the FFmpeg arguments start_transcode builds ----------------------------------------

def media_for(root: Path) -> streamer.MediaInfo:
    movie = root / "movie.mkv"
    movie.write_bytes(b"x")
    return streamer.MediaInfo(
        path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p", width=1280, height=720,
        fps=25.0, duration=120.0, audio_streams=[streamer.AudioTrack(index=0, codec="aac", default=True)])


def transcode_args(root: Path, **kwargs) -> tuple[list[str], streamer.Session]:
    session = streamer.Session()
    session.used_software_fallback = True
    proc = mock.MagicMock(pid=4242)
    proc.poll.return_value = None
    with mock.patch.object(streamer, "ROOT", root), \
         mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"), \
         mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"), \
         mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
         mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
         mock.patch.object(session, "_start_server"), \
         mock.patch.object(session, "_wait_for_segments", return_value=True), \
         mock.patch.object(streamer, "_save_session"), \
         mock.patch.object(streamer.time, "sleep"), \
         mock.patch.object(session, "_await_receiver"), \
         mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
        session.start_transcode(
            media_for(root), kwargs.pop("offset", 0.0), device="TV", quality="balanced",
            audio_profile="original", subs_file=None, burn_subs=False, title="Film", **kwargs)
    return popen.call_args_list[0].args[0], session


def af(args: list[str]) -> str | None:
    return args[args.index("-af") + 1] if "-af" in args else None


def test_no_delay_leaves_the_audio_graph_exactly_as_before(tmp_path):
    args, session = transcode_args(tmp_path)
    assert af(args) is None and session.state.audio_delay_ms == 0


def test_positive_and_negative_delay_reach_ffmpeg_and_the_saved_state(tmp_path):
    args, session = transcode_args(tmp_path, audio_delay_ms=300)
    assert af(args) == "adelay=delays=300:all=1" and session.state.audio_delay_ms == 300
    args, session = transcode_args(tmp_path, audio_delay_ms=-250)
    assert af(args) == "atrim=start=0.250,asetpts=PTS-STARTPTS" and session.state.audio_delay_ms == -250


def test_delay_is_the_last_audio_filter_so_it_is_measured_in_output_time(tmp_path):
    args, _ = transcode_args(tmp_path, speed=2.0, audio_delay_ms=300, offset=71.5)
    chain = af(args).split(",")
    assert chain[0] == "atempo=2" and chain[-1] == "adelay=delays=300:all=1"
    assert args[args.index("-ss") + 1] == "71.5"                           # a seek never changes the delay


def test_out_of_range_values_are_clamped_before_ffmpeg(tmp_path):
    args, session = transcode_args(tmp_path, audio_delay_ms=10**9)
    assert af(args) == "adelay=delays=5000:all=1" and session.state.audio_delay_ms == 5000
    args, _ = transcode_args(tmp_path, audio_delay_ms="oops")
    assert af(args) is None


def test_hardware_to_software_retry_keeps_the_delay(tmp_path):
    session = streamer.Session()
    session.used_software_fallback = False
    proc = mock.MagicMock(pid=4242)
    proc.poll.return_value = None
    with mock.patch.object(streamer, "ROOT", tmp_path), \
         mock.patch.object(streamer, "FFMPEG_LOG", tmp_path / "ffmpeg.log"), \
         mock.patch.object(streamer, "PROGRESS_FILE", tmp_path / "progress.log"), \
         mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
         mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
         mock.patch.object(session, "_start_server"), \
         mock.patch.object(session, "_wait_for_segments", side_effect=[False, True]), \
         mock.patch.object(streamer, "_terminate"), \
         mock.patch.object(streamer, "_save_session"), \
         mock.patch.object(streamer.time, "sleep"), \
         mock.patch.object(session, "_await_receiver"), \
         mock.patch.object(streamer.subprocess, "Popen", return_value=proc) as popen:
        session.start_transcode(media_for(tmp_path), 0.0, device="TV", quality="balanced",
                                audio_profile="original", subs_file=None, burn_subs=False,
                                title="Film", audio_delay_ms=-100)
    assert len(popen.call_args_list) >= 2
    for call in popen.call_args_list[:2]:
        assert af(call.args[0]) == "atrim=start=0.100,asetpts=PTS-STARTPTS"
    assert session.state.audio_delay_ms == -100


def test_saved_session_state_validates_the_new_field():
    base = {"file": "/f.mkv", "mode": "transcode", "offset": 0.0, "duration": 9.0,
            "device": "TV", "title": "T"}
    assert streamer._checked_state({**base, "audio_delay_ms": 250}).audio_delay_ms == 250
    for junk in ("250", None, 1.5, True, [1]):
        assert streamer._checked_state({**base, "audio_delay_ms": junk}).audio_delay_ms == 0
    assert streamer._checked_state(base).audio_delay_ms == 0               # sessions saved before this release


# --- DLNA conversion ---------------------------------------------------------------------

def dlna_args(tmp_path: Path, **kwargs) -> list[str]:
    source = tmp_path / "film.mkv"
    source.write_bytes(b"fake")
    media = streamer.MediaInfo(path=source, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                               width=1280, height=720, fps=24, duration=85)

    def make_file(args, **_kw):
        Path(args[-1]).write_bytes(b"mp4")
        proc = mock.MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        return proc

    with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as run:
        dlna.prepare_mp4(media, tmp_path / "out" / "movie.mp4", **kwargs)
    return run.call_args.args[0]


def test_dlna_copies_compatible_audio_unless_a_delay_needs_a_re_encode(tmp_path):
    plain = dlna_args(tmp_path)
    assert plain[plain.index("-c:a") + 1] == "copy" and "-af" not in plain
    positive = dlna_args(tmp_path, audio_delay_ms=300)
    assert positive[positive.index("-c:a") + 1] == "aac" and af(positive) == "adelay=delays=300:all=1"
    negative = dlna_args(tmp_path, audio_delay_ms=-300)
    assert negative[negative.index("-c:a") + 1] == "aac"
    assert af(negative) == "atrim=start=0.300,asetpts=PTS-STARTPTS"


def test_dlna_start_does_not_play_a_file_as_is_when_a_delay_is_set():
    source = (ROOT / "src" / "dlna.py").read_text(encoding="utf-8")
    start = source.split("    def start(self, media", 1)[1].split("def stop", 1)[0]
    assert "audio_delay.normalize(audio_delay_ms) == 0" in start and "audio_delay_ms=audio_delay_ms" in start


# --- live adjustment (the real mixin methods, no GTK) ---------------------------------------

def adjust_window(session=None, *, media=None, preview="", busy=False):
    jobs: list = []
    w, _jobs, saves = window("_adjust_audio_delay", "_restart_at")
    w.jobs, w.saves = jobs, saves
    w.session, w.busy, w.media, w._preview_path = session, busy, media, preview
    w._restart_at = mock.Mock()
    return w


def transcode_session(path="/film.mkv"):
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    session.state.file = path
    return session


def test_adjust_needs_a_film_and_is_saved_per_film():
    w = adjust_window()
    w._adjust_audio_delay(1)
    assert w.toast.called
    assert audio_delay_cfg(w) == {}
    w = adjust_window(preview="/film.mkv")
    w._adjust_audio_delay(1)
    assert audio_delay_cfg(w) == {"/film.mkv": 50}
    assert "applies when you cast" in w.toast.call_args.args[0]
    w._restart_at.assert_not_called()
    w._adjust_audio_delay(1)
    w._adjust_audio_delay(-1)
    w._adjust_audio_delay(-1)
    w._adjust_audio_delay(-1)
    assert audio_delay_cfg(w) == {"/film.mkv": -50}
    w._adjust_audio_delay(0)
    assert audio_delay_cfg(w) == {}
    w._adjust_audio_delay(0)
    assert w.toast.call_args.args[0] == "Audio delay already off"


def audio_delay_cfg(w):
    return w.cfg.get(ad.CONFIG_KEY, {})


def test_adjust_stops_at_the_limit_without_restarting():
    w = adjust_window(preview="/film.mkv")
    w.cfg[ad.CONFIG_KEY] = {"/film.mkv": 5000}
    w._adjust_audio_delay(1)
    assert "limit reached" in w.toast.call_args.args[0] and audio_delay_cfg(w) == {"/film.mkv": 5000}
    assert not w.saves


def test_live_transcode_restarts_at_the_current_position_and_saves_the_choice():
    session = transcode_session()
    w = adjust_window(session)
    w.tracker.start(88.0, 200.0, True)
    w._adjust_audio_delay(1)
    assert audio_delay_cfg(w) == {"/film.mkv": 50} and w.saves
    w._restart_at.assert_called_once()
    called_session, position = w._restart_at.call_args.args
    assert called_session is session and 87.0 <= position <= 120.0
    assert w.busy is True and "stream restarted" in w.toast.call_args.args[0]


def test_direct_play_is_not_restarted_and_says_why():
    session = transcode_session()
    session.mode = "direct"
    w = adjust_window(session)
    w._adjust_audio_delay(-1)
    assert audio_delay_cfg(w) == {"/film.mkv": -50}
    w._restart_at.assert_not_called()
    assert "direct play cannot be shifted" in w.toast.call_args.args[0] and w.busy is False


def test_a_busy_window_ignores_the_key_press():
    w = adjust_window(transcode_session(), busy=True)
    w._adjust_audio_delay(1)
    assert audio_delay_cfg(w) == {} and not w.saves
    w._restart_at.assert_not_called()
    assert w.toast.call_args.args[0].startswith("Hold on")


def test_restart_passes_the_saved_delay_to_the_new_encode():
    w, jobs, _ = window("_restart_at")
    w.jobs = jobs
    w.cfg[ad.CONFIG_KEY] = {str(Path("/film.mkv")): -250}   # the restart keys by str(media.path)
    session = mock.Mock()
    session.mode = "transcode"
    session.state = state()
    run_restart(w, session, paused=False)
    assert session.start_transcode.call_args.kwargs["audio_delay_ms"] == -250
    w.cfg[ad.CONFIG_KEY] = {}
    w2, jobs2, _ = window("_restart_at")
    w2.jobs = jobs2
    session2 = mock.Mock()
    session2.mode = "transcode"
    session2.state = state()
    run_restart(w2, session2, paused=False)
    assert session2.start_transcode.call_args.kwargs["audio_delay_ms"] == 0


# --- wiring ---------------------------------------------------------------------------------------

def test_cast_path_forces_a_transcode_and_passes_the_delay_to_every_encoder():
    text = (ROOT / "src" / "cast_session.py").read_text(encoding="utf-8")
    assert "adelay = audio_delay.get(cfg, path)" in text and "and not adelay" in text
    assert text.count("audio_delay_ms=adelay") == 2                          # DLNA start and HLS transcode
    assert "audio_delay_ms=audio_delay.get(self.cfg, file_path)" in text    # restarts
    assert len(text.encode("utf-8")) <= 48_000                               # the module's size cap


def test_menu_actions_and_shortcuts_exist():
    ui = (ROOT / "src" / "cast_ui.py").read_text(encoding="utf-8")
    for action in ("audio-earlier", "audio-later", "audio-reset"):
        assert f'"app.{action}"' in ui
    assert 'add("<Shift>g", lambda: self._adjust_audio_delay(-1))' in ui
    assert 'add("<Shift>h", lambda: self._adjust_audio_delay(1))' in ui
    control = (ROOT / "src" / "cast_control.py").read_text(encoding="utf-8")
    for direction, action in ((-1, "audio-earlier"), (1, "audio-later"), (0, "audio-reset")):
        assert f'simple("{action}", lambda *a: self._window()._adjust_audio_delay({direction}))' in control
    assert "AudioSyncMixin" in control
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for name in ('"audio_delay"', '"cast_audio_sync"', "src/audio_delay.py"):
        assert name in toml
    assert '"audio_delay_by_file": {}' in (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")


def test_the_extracted_helper_namespace_covers_the_new_module():
    names = {"audio_delay"}
    code = (ROOT / "src" / "cast_audio_sync.py").read_text(encoding="utf-8")
    assert all(f"{n}." in code for n in names)
