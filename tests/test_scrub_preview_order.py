"""Scrub previews: nearest-frame lookup, keyframe-fast decode, per-frame hover."""
from __future__ import annotations

import subprocess
import sys
from unittest import mock

import pytest

sys.path.insert(0, "src")

import screenshot  # noqa: E402

JPEG = b"\xff\xd8"


def test_nearest_ignores_other_films_generations_and_far_slots():
    cache = screenshot.SparseFrameCache()
    cache.put(cache.key("a.mkv", 1, 0, 0.0), b"\xff\xd8a")
    cache.put(cache.key("film.mkv", 2, 0, 20.0), b"\xff\xd8gen2")
    assert cache.nearest("film.mkv", 1, 0, 20.0) is None
    cache.put(cache.key("film.mkv", 1, 0, 10.0), b"\xff\xd8near")
    cache.put(cache.key("film.mkv", 1, 0, 40.0), b"\xff\xd8far")
    assert cache.nearest("film.mkv", 1, 0, 24.0) == (10.0, b"\xff\xd8near")
    assert cache.nearest("film.mkv", 1, 0, 1_000_000.0) is None
    assert cache.nearest("film.mkv", 1, 0, 11.0) == (10.0, b"\xff\xd8near")


@pytest.mark.parametrize("fast", [False, True])
def test_fast_preview_skips_the_accurate_seek_run_up(tmp_path, fast):
    movie = tmp_path / "film.mkv"
    movie.write_bytes(b"x")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, JPEG + b"jpeg", b"")

    with mock.patch.object(screenshot.subprocess, "run", fake_run), \
         mock.patch.object(screenshot.media_tools, "resolve_media_tool", lambda _n: "ffmpeg"):
        assert screenshot.preview_frame(movie, 61.5, fast=fast).startswith(JPEG)
    command = captured["command"]
    assert ("-noaccurate_seek" in command) is fast
    if fast:
        assert command.index("-noaccurate_seek") < command.index("-ss") < command.index("-i")



class FakeFrames:
    """A manual main loop: scheduled callbacks run only when told to."""

    def __init__(self):
        self.timers: dict[int, tuple[int, object]] = {}
        self.next_id = 1

    def schedule(self, delay, fn):
        self.timers[self.next_id] = (delay, fn)
        self.next_id += 1
        return self.next_id - 1

    def cancel(self, source):
        self.timers.pop(source, None)

    def run_frame(self):
        for source, (_delay, fn) in list(self.timers.items()):
            del self.timers[source]
            fn()


def test_pointer_motion_reaches_the_window_once_per_frame_with_the_newest_time():
    from hover_coalescer import HoverCoalescer

    frames, delivered = FakeFrames(), []
    hover = HoverCoalescer(delivered.append, schedule=frames.schedule, cancel=frames.cancel)
    for value in (1.0, 2.0, 3.0, 4.0):      # four motion events within one frame
        hover.push(value)
    assert delivered == [] and len(frames.timers) == 1   # one timer, not four
    frames.run_frame()
    assert delivered == [4.0] and not hover.pending
    hover.push(9.0)
    frames.run_frame()
    assert delivered == [4.0, 9.0]
    assert all(delay == 16 for delay, _fn in [(16, None)])  # one 60 Hz frame


def test_release_or_leave_drops_a_pending_motion_so_it_cannot_land_afterwards():
    from hover_coalescer import HoverCoalescer

    frames, delivered = FakeFrames(), []
    hover = HoverCoalescer(delivered.append, schedule=frames.schedule, cancel=frames.cancel)
    hover.push(5.0)
    hover.drop()                      # drag released / pointer left the bar
    frames.run_frame()
    assert delivered == [] and frames.timers == {} and not hover.pending
    hover.drop()                      # idempotent
    hover.push(6.0)                   # and usable again afterwards
    frames.run_frame()
    assert delivered == [6.0]
