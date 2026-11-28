"""Every encoder start leaves its own attempt folder; retries never erase evidence (#698).

ffmpeg.log is truncated on each start, so a hardware stall followed by a software
retry used to leave an empty tail. These tests drive the real start_transcode with
the encoder, server and receiver mocked: no GTK, no network, no real receiver.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import attempt_log
import diagnose_bundle
import failure_boundary
import streamer

SECRET_NAME = "private-holiday-video.mkv"


def _media(root: Path) -> streamer.MediaInfo:
    movie = root / SECRET_NAME
    movie.write_bytes(b"x")
    return streamer.MediaInfo(
        path=movie, vcodec="h264", acodec="aac", pix_fmt="yuv420p", width=1280, height=720,
        fps=25.0, duration=120.0, audio_streams=[streamer.AudioTrack(index=0, codec="aac", default=True)])


def start(tmp_path: Path, *, software=True, segments=(True,), stderr=("encoder line\n",),
          server_error=None, receiver_error=None):
    """Run one start_transcode; returns (cache_root, exception_or_None)."""
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    log = tmp_path / "ffmpeg.log"
    session = streamer.Session()
    session.used_software_fallback = software
    proc = mock.MagicMock(pid=4242)
    proc.poll.return_value = None
    lines = iter(stderr)

    def popen(args, *a, **k):
        if "hls" in args:  # the encoder: the log was opened "w" just before, as in production
            with open(log, "a") as handle:
                handle.write(next(lines, ""))
        return proc

    error = None
    with mock.patch.object(streamer, "ROOT", tmp_path), \
         mock.patch.object(streamer, "FFMPEG_LOG", log), \
         mock.patch.object(streamer, "PROGRESS_FILE", tmp_path / "progress.log"), \
         mock.patch.object(streamer.paths, "cache_dir", return_value=cache), \
         mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"), \
         mock.patch.object(streamer, "require_compatible_ffmpeg", return_value=(7, 0)), \
         mock.patch.object(session, "_start_server", side_effect=server_error), \
         mock.patch.object(session, "_wait_for_segments", side_effect=list(segments)), \
         mock.patch.object(streamer, "_save_session"), \
         mock.patch.object(streamer, "_terminate"), \
         mock.patch.object(streamer.time, "sleep"), \
         mock.patch.object(session, "_await_receiver", side_effect=receiver_error), \
         mock.patch.object(streamer.subprocess, "Popen", side_effect=popen):
        try:
            session.start_transcode(
                _media(tmp_path), 0.0, device="TV", quality="balanced", audio_profile="original",
                subs_file=None, burn_subs=False, title="Film")
        except Exception as exc:  # noqa: BLE001 - the tests assert on it
            error = exc
    return cache, error


def attempts(cache: Path) -> list[dict]:
    out = []
    for folder in sorted((cache / "attempts").iterdir()):
        files = {p.name: p.read_text() for p in folder.iterdir()}
        out.append({"folder": folder.name, "files": files,
                    "outcome": json.loads(files["outcome.json"]) if "outcome.json" in files else None})
    return out


def test_successful_start_records_argv_plan_stderr_and_outcome(tmp_path):
    cache, error = start(tmp_path, stderr=("frame=1 fps=25\n",))
    assert error is None
    (attempt,) = attempts(cache)
    assert attempt["outcome"]["outcome"] == "started"
    assert "software encode" in attempt["files"]["plan.txt"]
    argv = json.loads(attempt["files"]["argv.json"])
    assert "hls" in argv and any(SECRET_NAME in part for part in argv)
    assert attempt["files"]["ffmpeg.log"] == "frame=1 fps=25\n"


def test_stall_on_software_fails_with_tail_plan_and_a_kept_log(tmp_path):
    cache, error = start(tmp_path, segments=(False,), stderr=("Impossible to convert\n",))
    assert isinstance(error, streamer.StreamError)
    assert error.code == "ffmpeg.encoder_stalled"
    failure = failure_boundary.describe(error)
    assert failure.code == "ffmpeg.encoder_stalled"
    assert failure.message == streamer.errors.CATALOGUE["ffmpeg.encoder_stalled"].message
    assert "software encode" in str(error) and "Impossible to convert" in str(error)
    (attempt,) = attempts(cache)
    assert attempt["outcome"]["outcome"] == "failed"
    assert "no media segments" in attempt["outcome"]["reason"]
    assert "Impossible to convert" in attempt["files"]["ffmpeg.log"]


def test_hardware_stall_then_software_retry_keeps_both_attempts_and_the_first_log(tmp_path):
    cache, error = start(tmp_path, software=False, segments=(False, True),
                         stderr=("vaapi: device hung\n", "software ok\n"))
    assert error is None
    first, second = attempts(cache)
    assert first["outcome"]["outcome"] == "stalled-retry-software"
    assert "hardware encode" in first["files"]["plan.txt"]
    # The retry truncated ffmpeg.log; the first attempt's evidence must survive anyway.
    assert first["files"]["ffmpeg.log"] == "vaapi: device hung\n"
    assert second["outcome"]["outcome"] == "started"
    assert "software encode" in second["files"]["plan.txt"]
    assert second["files"]["ffmpeg.log"] == "software ok\n"
    assert first["folder"] != second["folder"]


def test_server_start_failure_is_recorded_and_still_raises(tmp_path):
    cache, error = start(tmp_path, server_error=RuntimeError("port busy"))
    assert isinstance(error, RuntimeError)
    (attempt,) = attempts(cache)
    assert attempt["outcome"]["outcome"] == "failed"
    assert "port busy" in attempt["outcome"]["reason"]


def test_receiver_refusal_is_recorded_and_still_raises(tmp_path):
    cache, error = start(tmp_path, receiver_error=RuntimeError("TV said no"))
    assert isinstance(error, RuntimeError)
    (attempt,) = attempts(cache)
    assert attempt["outcome"]["outcome"] == "failed"
    assert "TV said no" in attempt["outcome"]["reason"]


def test_a_broken_diagnostics_layer_never_breaks_a_cast_but_is_reported(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="smoothcast.attempts"), \
         mock.patch.object(attempt_log, "begin", side_effect=OSError("disk full")):
        cache, error = start(tmp_path)
    assert error is None
    assert not (cache / "attempts").exists()
    assert "disk full" in caplog.text  # never silent


@pytest.mark.parametrize("software,segments", [(True, (True,)), (False, (False, True))])
def test_attempt_folder_count_is_bounded(tmp_path, software, segments):
    cache = tmp_path / "cache"
    for number in range(attempt_log.KEEP + 5):
        attempt_log.begin(cache, argv=["ffmpeg"], plan_reason=f"old {number}").finish("started")
    start(tmp_path, software=software, segments=segments)
    assert len(list((cache / "attempts").iterdir())) <= attempt_log.KEEP


def test_diagnostics_bundle_shows_attempts_without_media_paths(tmp_path):
    cache, _ = start(tmp_path, segments=(False,), stderr=(f"error opening {tmp_path}/{SECRET_NAME}\n",))
    text = json.dumps(diagnose_bundle.collect(cache))
    assert "Impossible" not in text and "attempts" in text
    assert SECRET_NAME not in text and str(tmp_path) not in text
