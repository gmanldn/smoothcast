"""A slow but advancing encoder is not killed by the fixed start-up window (#686)."""
from types import SimpleNamespace

import progress_model
import streamer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _session(monkeypatch, tmp_path, progress_at, *, alive=True):
    clock = Clock()
    monkeypatch.setattr(streamer.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(streamer.time, "sleep", clock.sleep)
    monkeypatch.setattr(streamer, "ROOT", tmp_path)
    session = streamer.Session.__new__(streamer.Session)
    session._playlist_name = "movie-" + "a" * 32 + ".m3u8"
    session._segment_pattern = "segment-" + "a" * 32 + "-*.ts"
    session.ffmpeg = SimpleNamespace(poll=lambda: None if alive else 1, returncode=None if alive else 1)
    session._read_progress = lambda path=None: progress_at(clock.now)
    return clock, session


def test_advancing_encoder_gets_past_the_initial_window_up_to_the_cap(monkeypatch, tmp_path):
    start = 1000.0

    def progress(now):
        return progress_model.Progress(out_time=(now - start) / 10.0, frame=int(now - start))

    clock, session = _session(monkeypatch, tmp_path, progress)
    assert session._wait_for_segments(30) is False
    assert 119.0 <= clock.now - start <= 121.0


def test_advancing_encoder_succeeds_when_segments_arrive_after_30s(monkeypatch, tmp_path):
    start = 1000.0

    def progress(now):
        if now - start >= 50:
            (tmp_path / session._playlist_name).write_text("#EXTM3U\n")
            for i in range(2):
                (tmp_path / f"segment-{'a' * 32}-{i:05d}.ts").write_bytes(b"x")
        return progress_model.Progress(out_time=(now - start) / 10.0, frame=int(now - start))

    clock, session = _session(monkeypatch, tmp_path, progress)
    assert session._wait_for_segments(30) is True
    assert clock.now - start < 60


def test_frozen_progress_still_fails_at_the_initial_timeout(monkeypatch, tmp_path):
    clock, session = _session(monkeypatch, tmp_path,
                              lambda now: progress_model.Progress(out_time=1.0, frame=5))
    assert session._wait_for_segments(15) is False
    assert clock.now - 1000.0 <= 15.5


def test_no_progress_file_keeps_the_old_window(monkeypatch, tmp_path):
    clock, session = _session(monkeypatch, tmp_path, lambda now: progress_model.EMPTY)
    assert session._wait_for_segments(15) is False
    assert clock.now - 1000.0 <= 15.5


def test_dead_encoder_fails_at_once(monkeypatch, tmp_path):
    clock, session = _session(monkeypatch, tmp_path,
                              lambda now: progress_model.EMPTY, alive=False)
    session._playlist_is_complete = lambda playlist: False
    assert session._wait_for_segments(30) is False
    assert clock.now - 1000.0 < 1
