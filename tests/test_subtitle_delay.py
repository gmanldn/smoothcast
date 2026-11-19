"""Subtitle delay: limits, persistence, restart plumbing and real burn-in timing.

Headless only: no GTK, no receiver, no desktop window. The FFmpeg tests render
real frames and measure *when* a cue becomes visible.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import config_control
import streamer
import subtitle_delay
import subtitle_restart


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    (0, 0), (100, 100), (-100, -100), (149.6, 150), (-0.4, 0),
    (10**9, subtitle_delay.LIMIT_MS), (-10**9, -subtitle_delay.LIMIT_MS),
    (True, 0), (False, 0), ("200", 0), (None, 0), ([], 0),
    (float("nan"), 0), (float("inf"), 0), (float("-inf"), 0),
])
def test_normalize_is_total_and_bounded(raw, expected):
    assert subtitle_delay.normalize(raw) == expected


def test_step_moves_100ms_and_clamps():
    assert subtitle_delay.step(0, 1) == 100
    assert subtitle_delay.step(0, -1) == -100
    assert subtitle_delay.step(100, -1) == 0
    assert subtitle_delay.step(250, 1) == 350
    assert subtitle_delay.step(300, 0) == 300
    assert subtitle_delay.step(subtitle_delay.LIMIT_MS, 1) == subtitle_delay.LIMIT_MS
    assert subtitle_delay.step(-subtitle_delay.LIMIT_MS, -1) == -subtitle_delay.LIMIT_MS
    assert subtitle_delay.step("garbage", 1) == 100


def test_label_reads_naturally():
    assert subtitle_delay.label(0) == "Off"
    assert subtitle_delay.label(300) == "+0.3 s"
    assert subtitle_delay.label(-1500) == "−1.5 s"
    assert subtitle_delay.label(1250) == "+1.25 s"
    assert subtitle_delay.label(None) == "Off"


def test_filter_shift_none_when_nothing_to_do():
    assert subtitle_delay.filter_shift(0.0, 0) is None
    assert subtitle_delay.filter_shift(0.0, None) is None
    assert subtitle_delay.filter_shift(8.0, 8000) is None  # exactly cancels


def test_filter_shift_combines_seek_offset_and_delay():
    # Cue at source time s shows when the encode clock reads s + delay - offset.
    assert subtitle_delay.filter_shift(0.0, 1500) == (
        "setpts=PTS-1.500/TB", "setpts=PTS+1.500/TB")
    assert subtitle_delay.filter_shift(0.0, -1000) == (
        "setpts=PTS+1.000/TB", "setpts=PTS-1.000/TB")
    assert subtitle_delay.filter_shift(8.0, 1500) == (
        "setpts=PTS+6.500/TB", "setpts=PTS-6.500/TB")
    assert subtitle_delay.filter_shift(8.0, 0) == (
        "setpts=PTS+8.000/TB", "setpts=PTS-8.000/TB")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -5.0, "x", None])
def test_filter_shift_ignores_unusable_offsets(bad):
    assert subtitle_delay.filter_shift(bad, 100) == (
        "setpts=PTS-0.100/TB", "setpts=PTS+0.100/TB")


def test_store_roundtrip_and_zero_clears():
    cfg: dict = {}
    assert subtitle_delay.get(cfg, "/m/a.mkv") == 0
    assert subtitle_delay.put(cfg, "/m/a.mkv", 300) == 300
    assert subtitle_delay.get(cfg, pathlib.Path("/m/a.mkv")) == 300
    assert subtitle_delay.get(cfg, "/m/b.mkv") == 0
    assert subtitle_delay.put(cfg, "/m/a.mkv", 0) == 0
    assert cfg["subtitle_delay_by_file"] == {}


def test_store_survives_corrupt_values():
    assert subtitle_delay.get({"subtitle_delay_by_file": "nope"}, "x") == 0
    assert subtitle_delay.get({"subtitle_delay_by_file": {"x": "9"}}, "x") == 0
    assert subtitle_delay.get(None, "x") == 0
    cfg = {"subtitle_delay_by_file": ["bad"]}
    subtitle_delay.put(cfg, "x", 100)
    assert cfg["subtitle_delay_by_file"] == {"x": 100}


def test_store_is_bounded_and_evicts_oldest():
    cfg: dict = {}
    for index in range(subtitle_delay.MAX_ENTRIES + 5):
        subtitle_delay.put(cfg, f"/m/{index}.mkv", 100)
    saved = cfg["subtitle_delay_by_file"]
    assert len(saved) == subtitle_delay.MAX_ENTRIES
    assert "/m/0.mkv" not in saved
    assert f"/m/{subtitle_delay.MAX_ENTRIES + 4}.mkv" in saved


def test_config_sanitiser_keeps_only_valid_delays():
    defaults = {"subtitle_delay_by_file": {}}
    raw = {"subtitle_delay_by_file": {
        "/ok.mkv": 300, "/neg.mkv": -1500, "/zero.mkv": 0, "/bool.mkv": True,
        "/float.mkv": 1.5, "/huge.mkv": 10**9, "": 100, 7: 100,
    }}
    assert config_control.sanitise_config(raw, defaults) == {
        "subtitle_delay_by_file": {"/ok.mkv": 300, "/neg.mkv": -1500}}
    assert config_control.sanitise_config(
        {"subtitle_delay_by_file": "x"}, defaults) == defaults


# --------------------------------------------------------------------------
# Filter graph construction
# --------------------------------------------------------------------------

def _args(**overrides):
    params = dict(burn_subs=True, staged=pathlib.Path("subs.srt"), software=True,
                  speed=1.0, rotation=0)
    params.update(overrides)
    return streamer.Session()._filter_args(**params)


def test_unshifted_burn_in_keeps_the_existing_graph():
    assert _args() == ["-vf", "subtitles=filename=subs.srt"]


def test_no_subtitles_means_no_shift_filters():
    assert _args(burn_subs=False, subtitle_delay_ms=500, subtitle_offset=9.0) == []


def test_delay_wraps_only_the_subtitle_filter():
    assert _args(subtitle_delay_ms=1500) == [
        "-vf", "setpts=PTS-1.500/TB,subtitles=filename=subs.srt,setpts=PTS+1.500/TB"]


def test_shift_runs_in_source_time_before_speed_and_rotation():
    vf = _args(subtitle_delay_ms=500, speed=2.0, rotation=90)[1]
    assert vf == ("setpts=PTS-0.500/TB,subtitles=filename=subs.srt,"
                  "setpts=PTS+0.500/TB,setpts=PTS/2,transpose=1")


def test_embedded_track_is_shifted_too():
    vf = _args(burn_subs=False, staged=None, embedded_subtitle_index=1,
               embedded_source=pathlib.Path("/m/film.mkv"),
               subtitle_offset=30.0, subtitle_delay_ms=-200)[1]
    assert vf == ("setpts=PTS+30.200/TB,subtitles=filename=/m/film.mkv:si=1,"
                  "setpts=PTS-30.200/TB")


def test_hardware_path_keeps_the_shift_inside_the_software_section():
    vf = _args(software=False, subtitle_delay_ms=300)[1]
    assert vf == ("hwdownload,format=nv12,setpts=PTS-0.300/TB,"
                  "subtitles=filename=subs.srt,setpts=PTS+0.300/TB,hwupload")


# --------------------------------------------------------------------------
# Restart plumbing
# --------------------------------------------------------------------------

def _media(tracks=()):
    return SimpleNamespace(subtitle_tracks=list(tracks))


def test_restart_without_state_has_no_delay():
    result = subtitle_restart.validate_restart(None, _media(), 500)
    assert result == subtitle_restart.RestartSubtitles(None, False, None, 0)


def test_restart_burns_a_receiver_sidecar_when_delayed(tmp_path):
    sidecar = tmp_path / "film.srt"
    sidecar.write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n", encoding="utf-8")
    state = SimpleNamespace(subs=str(sidecar), burn_subs=False,
                            embedded_subtitle_index=-1, subtitle_delay_ms=0)
    plain = subtitle_restart.validate_restart(state, _media())
    assert (plain.burn, plain.delay_ms) == (False, 0)
    delayed = subtitle_restart.validate_restart(state, _media(), 300)
    assert (delayed.burn, delayed.delay_ms) == (True, 300)
    # An explicit zero resets even when the stream had been delayed.
    state.subtitle_delay_ms = 700
    assert subtitle_restart.validate_restart(state, _media()).delay_ms == 700
    assert subtitle_restart.validate_restart(state, _media(), 0).delay_ms == 0


def test_restart_clamps_hostile_delay_values():
    state = SimpleNamespace(subs="", burn_subs=False, embedded_subtitle_index=-1,
                            subtitle_delay_ms=10**12)
    assert (subtitle_restart.validate_restart(state, _media()).delay_ms
            == subtitle_delay.LIMIT_MS)


def test_session_state_defaults_and_old_files_still_load():
    state = streamer.SessionState(file="f", mode="transcode", offset=0.0,
                                  duration=1.0, device="d", title="t")
    assert state.subtitle_delay_ms == 0
    assert "subtitle_delay_ms" in streamer.SessionState.__dataclass_fields__


# --------------------------------------------------------------------------
# Real FFmpeg: measure when the cue is actually visible
# --------------------------------------------------------------------------

np = pytest.importorskip("numpy")
FFMPEG = shutil.which("ffmpeg")


def _has_filter(name: str) -> bool:
    if not FFMPEG:
        return False
    out = subprocess.run([FFMPEG, "-hide_banner", "-filters"],
                         capture_output=True, text=True).stdout
    return f" {name} " in out


needs_libass = pytest.mark.skipif(
    not _has_filter("subtitles"), reason="FFmpeg with libass is required")

WIDTH, HEIGHT, FPS = 320, 180, 10
CUE_START, CUE_END = 10.0, 12.0


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("sub-delay")
    (folder / "cue.srt").write_text(
        "1\n00:00:10,000 --> 00:00:12,000\nHELLO HELLO HELLO\n\n", encoding="utf-8")
    run = lambda *args: subprocess.run(  # noqa: E731
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True, cwd=folder)
    run("-f", "lavfi", "-i", f"color=c=black:s={WIDTH}x{HEIGHT}:r=25:d=20",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "plain.mp4")
    run("-i", "plain.mp4", "-i", "cue.srt", "-map", "0:v", "-map", "1:0",
        "-c:v", "copy", "-c:s", "srt", "embedded.mkv")
    return folder


def _visible_window(folder, source, *, offset, delay_ms, embedded=None):
    """(first, last) seconds of the *output* where the cue is drawn."""
    options = dict(burn_subs=embedded is None,
                   staged=None if embedded is not None else pathlib.Path("cue.srt"),
                   software=True, speed=1.0, rotation=0,
                   subtitle_offset=offset, subtitle_delay_ms=delay_ms)
    if embedded is not None:
        options.update(embedded_subtitle_index=0,
                       embedded_source=folder / embedded)
    vf = streamer.Session()._filter_args(**options)[1]
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if offset:
        cmd += ["-ss", str(offset)]
    cmd += ["-i", str(folder / source), "-an",
            "-vf", f"{vf},fps={FPS},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True, cwd=folder).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, HEIGHT, WIDTH)
    lit = [i / FPS for i, frame in enumerate(frames) if (frame > 128).sum() > 50]
    assert lit, "the cue was never drawn"
    return lit[0], lit[-1]


def _close(window, start, end):
    first, last = window
    return abs(first - start) <= 0.15 and abs(last - (end - 1 / FPS)) <= 0.15


@needs_libass
@pytest.mark.parametrize("delay_ms, start", [
    (0, 10.0), (1500, 11.5), (-1000, 9.0), (100, 10.1), (-100, 9.9),
])
def test_burned_cue_moves_by_exactly_the_requested_delay(media_dir, delay_ms, start):
    window = _visible_window(media_dir, "plain.mp4", offset=0.0, delay_ms=delay_ms)
    assert _close(window, start, start + (CUE_END - CUE_START)), window


@needs_libass
def test_resumed_stream_shows_cues_at_the_right_film_time(media_dir):
    """Regression: with -ss, libass used encode time, so cues came ~offset late."""
    window = _visible_window(media_dir, "plain.mp4", offset=8.0, delay_ms=0)
    assert _close(window, 2.0, 4.0), window  # film 10-12 s == output 2-4 s


@needs_libass
def test_resume_and_delay_combine(media_dir):
    window = _visible_window(media_dir, "plain.mp4", offset=8.0, delay_ms=1500)
    assert _close(window, 3.5, 5.5), window


@needs_libass
def test_embedded_track_timing_follows_offset_and_delay(media_dir):
    plain = _visible_window(media_dir, "embedded.mkv", offset=0.0, delay_ms=0,
                            embedded="embedded.mkv")
    assert _close(plain, 10.0, 12.0), plain
    shifted = _visible_window(media_dir, "embedded.mkv", offset=8.0, delay_ms=-500,
                              embedded="embedded.mkv")
    assert _close(shifted, 1.5, 3.5), shifted


@needs_libass
def test_shift_does_not_change_frame_count(media_dir):
    """Wrapping the subtitle filter must leave the video timeline untouched."""
    def frame_count(delay_ms):
        vf = streamer.Session()._filter_args(
            True, pathlib.Path("cue.srt"), True, 1.0, 0,
            subtitle_offset=0.0, subtitle_delay_ms=delay_ms)[1]
        raw = subprocess.run(
            [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", "plain.mp4", "-an",
             "-vf", f"{vf},fps={FPS},format=gray", "-f", "rawvideo", "-"],
            capture_output=True, check=True, cwd=media_dir).stdout
        return len(raw) // (WIDTH * HEIGHT)
    assert frame_count(0) == frame_count(2500) == frame_count(-2500) == 20 * FPS
