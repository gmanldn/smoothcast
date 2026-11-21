"""Per-track music gain analysis and true-peak-safe filter generation."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import loudness

sys.path.insert(0, str(ROOT / "src"))
import streamer


FFMPEG = shutil.which("ffmpeg")


def _log(*, integrated="-26.0", peak="-8.0", lra="1.0", threshold="-36.0"):
    return "ffmpeg output\n" + json.dumps({
        "input_i": integrated,
        "input_tp": peak,
        "input_lra": lra,
        "input_thresh": threshold,
        "target_offset": "0.0",
    })


def test_parse_analysis_rejects_silence_and_non_finite_fields():
    assert loudness.parse_analysis(_log()) == loudness.Analysis(-26.0, -8.0, 1.0, -36.0)
    assert loudness.parse_analysis(_log(integrated="-inf")) is None
    assert loudness.parse_analysis(_log(peak="nan")) is None
    assert loudness.parse_analysis("no loudnorm stats") is None


def test_cached_filter_uses_measured_stats_and_clamps_user_offset():
    analysis = loudness.Analysis(-26.0, -8.0, 1.0, -36.0)
    value = loudness.music_filter(analysis, manual_offset_db=24)
    assert "I=-16:TP=-1.5:LRA=11" in value
    assert "measured_I=-26" in value
    assert "measured_TP=-8" in value
    assert "measured_LRA=1" in value
    assert "linear=true" in value
    assert "offset=6" in value
    assert "nan" not in value and "inf" not in value


def test_monitor_reports_actual_autogain_path_and_passthrough_fallback():
    base = dict(file="song.wav", mode="transcode", offset=0, duration=1,
                device="fixture", title="Music")
    measured = streamer.SessionState(
        **base, music_autogain=True, music_autogain_measured=True)
    chain, hint = streamer.monitor_summary("original", 0.0, streamer.state_loudness(measured))
    assert chain[-1] == loudness.music_filter(None)
    assert "Music autogain (measured)" in hint
    fallback = streamer.SessionState(**base, music_autogain=True)
    _, hint = streamer.monitor_summary("original", 0.0, streamer.state_loudness(fallback))
    assert "Music autogain (streaming fallback)" in hint
    hint = streamer.music_hint_not_applied(
        "DLNA progressive MP4", SimpleNamespace(is_audio_only=True),
        {"music_autogain": True},
    )
    assert "not applied" in hint


def test_cache_key_includes_file_fingerprint_track_profile_and_mix(tmp_path):
    path = tmp_path / "song.flac"
    path.write_bytes(b"first")
    key = loudness.cache_key(path, 0, "original", None)
    assert key == loudness.cache_key(path, 0, "original", None)
    assert key != loudness.cache_key(path, 1, "original", None)
    assert key != loudness.cache_key(path, 0, "dialogue", None)
    assert key != loudness.cache_key(path, 0, "original", "pan=stereo|c0=c0|c1=c1")
    path.write_bytes(b"changed")
    assert key != loudness.cache_key(path, 0, "original", None)


@pytest.mark.skipif(not FFMPEG, reason="FFmpeg integration requires the local binary")
@pytest.mark.parametrize("gain_db", [-26, -12])
def test_analysis_and_measured_normalisation_hit_music_target(tmp_path, gain_db):
    source = tmp_path / f"tone-{gain_db}.wav"
    output = tmp_path / f"normalised-{gain_db}.wav"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=3:sample_rate=48000",
        "-af", f"volume={gain_db}dB", str(source),
    ], check=True, capture_output=True, timeout=30)
    analysis = loudness.analyze(source, 0, "original", cache_file=tmp_path / "cache.json")
    assert analysis is not None
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-af", loudness.music_filter(analysis), str(output),
    ], check=True, capture_output=True, timeout=30)
    measured = subprocess.run([
        FFMPEG, "-hide_banner", "-nostats", "-i", str(output),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ], capture_output=True, text=True, timeout=30)
    result = loudness.parse_analysis(measured.stderr)
    assert result is not None
    assert abs(result.integrated_lufs - (-16.0)) <= 1.0
    assert result.true_peak_db <= -1.5


@pytest.mark.skipif(not FFMPEG, reason="FFmpeg integration requires the local binary")
def test_cast_transcode_uses_cached_analysis_or_fast_streaming_fallback(tmp_path, monkeypatch):
    source = tmp_path / "music.wav"
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=2:sample_rate=48000", str(source),
    ], check=True, capture_output=True, timeout=30)
    media = streamer.ffprobe(source)
    other = tmp_path / "music-uncached.wav"
    shutil.copyfile(source, other)
    other_media = streamer.ffprobe(other)
    cache_file = tmp_path / "music-autogain.json"
    key = loudness.cache_key(source, 0, "original", None)
    loudness._cache_write(cache_file, key, loudness.Analysis(-26.0, -8.0, 1.0, -36.0))
    monkeypatch.setattr(loudness, "analysis_cache_path", lambda: cache_file)
    monkeypatch.setattr(streamer, "ROOT", tmp_path)
    monkeypatch.setattr(streamer, "SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr(streamer, "PROGRESS_FILE", tmp_path / "progress.log")
    monkeypatch.setattr(streamer, "FFMPEG_LOG", tmp_path / "ffmpeg.log")
    monkeypatch.setattr(streamer, "require_compatible_ffmpeg", lambda: None)
    monkeypatch.setattr(streamer.cache_privacy, "ensure_private_directory", lambda _path: None)
    monkeypatch.setattr(streamer.process_priority, "enabled", lambda: False)
    monkeypatch.setattr(streamer.process_priority, "launch_kwargs", lambda _low: {})
    monkeypatch.setattr(streamer.process_priority, "lower", lambda *_args: None)
    monkeypatch.setattr(streamer.process_identity, "start_time", lambda _pid: 1.0)

    captured = []

    class FakeProcess:
        pid = 123
        returncode = None

        def poll(self):
            return self.returncode

    monkeypatch.setattr(
        streamer.subprocess, "Popen",
        lambda args, **_kwargs: captured.append(args) or FakeProcess(),
    )
    session = streamer.Session(port=48123)
    session._vaapi_known_bad = lambda: False
    session._start_server = lambda *_args, **_kwargs: None
    session._start_sampler = lambda: None
    session._wait_for_segments = lambda _timeout: True
    session._await_receiver = lambda *_args, **_kwargs: None
    assert media.is_audio_only
    session.start_transcode(
        media, 0, device="fixture", quality="balanced", audio_profile="original",
        subs_file=None, burn_subs=False, title="Music", music_autogain=True,
    )
    encoder = captured[0]
    audio_filter = encoder[encoder.index("-af") + 1]
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-26.000" in audio_filter
    assert session.state.music_autogain is True
    assert session.state.music_autogain_measured is True

    # A second uncached track does not delay startup; it receives one-pass R128.
    session = streamer.Session(port=48123)
    session._vaapi_known_bad = lambda: False
    session._start_server = lambda *_args, **_kwargs: None
    session._start_sampler = lambda: None
    session._wait_for_segments = lambda _timeout: True
    session._await_receiver = lambda *_args, **_kwargs: None
    session.start_transcode(
        other_media, 0, device="fixture", quality="balanced", audio_profile="original",
        subs_file=None, burn_subs=False, title="Music", music_autogain=True,
    )
    audio_filter = captured[2][captured[2].index("-af") + 1]
    assert audio_filter == "loudnorm=I=-16:TP=-1.5:LRA=11"
    assert session.state.music_autogain is True
    assert session.state.music_autogain_measured is False
