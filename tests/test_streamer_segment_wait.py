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


GEN = "a" * 32


def _write_hls(root, playlist, names, *, init=None, endlist=False, empty=()):
    """Write a playlist that lists *names*, plus the segment files (and init) it names."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-TARGETDURATION:4"]
    if init:
        lines.append(f'#EXT-X-MAP:URI="{init}"')
        (root / init).write_bytes(b"init")
    for name in names:
        lines += ["#EXTINF:4.0,", name]
        if "/" not in name:
            (root / name).write_bytes(b"" if name in empty else b"segment")
    if endlist:
        lines.append("#EXT-X-ENDLIST")
    (root / playlist).write_text("\n".join(lines) + "\n")


def _ts(i, gen=GEN):
    return f"segment-{gen}-{i:05d}.ts"


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
            _write_hls(tmp_path, session._playlist_name, [
                f"segment-{'a' * 32}-{i:05d}.ts" for i in range(2)])
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


def _ready(monkeypatch, tmp_path, *, timeout=2, alive=True):
    clock, session = _session(monkeypatch, tmp_path, lambda now: progress_model.EMPTY, alive=alive)
    return clock, session, session._wait_for_segments(timeout)


def test_two_stray_files_do_not_unlock_playback(monkeypatch, tmp_path):
    (tmp_path / session_playlist()).write_text("#EXTM3U\n")
    for i in range(2):
        (tmp_path / _ts(i)).write_bytes(b"x")
    assert _ready(monkeypatch, tmp_path)[2] is False


def session_playlist():
    return f"movie-{GEN}.m3u8"


def test_two_listed_complete_segments_unlock_playback(monkeypatch, tmp_path):
    _write_hls(tmp_path, session_playlist(), [_ts(0), _ts(1)])
    clock, _session_, ready = _ready(monkeypatch, tmp_path)
    assert ready is True and clock.now - 1000.0 < 1


def test_one_listed_segment_or_a_missing_or_empty_one_is_not_enough(monkeypatch, tmp_path):
    _write_hls(tmp_path, session_playlist(), [_ts(0)])
    assert _ready(monkeypatch, tmp_path)[2] is False
    _write_hls(tmp_path, session_playlist(), [_ts(0), _ts(1)], empty={_ts(1)})
    assert _ready(monkeypatch, tmp_path)[2] is False
    _write_hls(tmp_path, session_playlist(), [_ts(0), _ts(1)])
    (tmp_path / _ts(1)).unlink()
    assert _ready(monkeypatch, tmp_path)[2] is False


def test_listed_names_must_belong_to_this_generation_and_stay_in_the_cache(monkeypatch, tmp_path):
    other = "b" * 32
    _write_hls(tmp_path, session_playlist(), [_ts(0), _ts(0, other)])
    assert _ready(monkeypatch, tmp_path)[2] is False
    outside = tmp_path.parent / "elsewhere.ts"
    outside.write_bytes(b"x")
    _write_hls(tmp_path, session_playlist(), [_ts(0), "../elsewhere.ts"])
    assert _ready(monkeypatch, tmp_path)[2] is False


def test_fmp4_generation_needs_its_nonempty_init_segment(monkeypatch, tmp_path):
    clock, session = _session(monkeypatch, tmp_path, lambda now: progress_model.EMPTY)
    session._playlist_name = f"movie-{GEN}-fmp4.m3u8"
    names = [f"segment-{GEN}-{i:05d}.m4s" for i in range(2)]
    init = f"init-{GEN}.mp4"
    _write_hls(tmp_path, session._playlist_name, names, init=init)
    assert session._wait_for_segments(2) is True
    (tmp_path / init).write_bytes(b"")
    assert session._wait_for_segments(2) is False
    (tmp_path / init).unlink()
    assert session._wait_for_segments(2) is False
    _write_hls(tmp_path, session._playlist_name, names)           # no EXT-X-MAP at all
    assert session._wait_for_segments(2) is False


def test_a_finished_one_segment_clip_is_still_accepted_when_the_encoder_exits_cleanly(
        monkeypatch, tmp_path):
    clock, session = _session(monkeypatch, tmp_path, lambda now: progress_model.EMPTY, alive=False)
    session.ffmpeg = SimpleNamespace(poll=lambda: 0, returncode=0)
    _write_hls(tmp_path, session_playlist(), [_ts(0)], endlist=True)
    assert session._wait_for_segments(30) is True
    assert clock.now - 1000.0 < 1


def test_the_waiter_never_walks_the_cache_directory(monkeypatch, tmp_path):
    for i in range(10_000):
        (tmp_path / f"unrelated-{i:05d}.bin").write_bytes(b"")
    _write_hls(tmp_path, session_playlist(), [_ts(0), _ts(1)])
    walks = []
    path_type = type(tmp_path)
    for name in ("glob", "rglob", "iterdir"):
        monkeypatch.setattr(path_type, name,
                            lambda self, *a, _n=name, **k: walks.append(_n) or iter(()))
    for name in ("scandir", "listdir", "walk"):
        monkeypatch.setattr(streamer.os, name,
                            lambda *a, _n=name, **k: walks.append(_n) or iter(()))
    clock, session = _session(monkeypatch, tmp_path, lambda now: progress_model.EMPTY)
    assert session._wait_for_segments(2) is True
    assert walks == []
