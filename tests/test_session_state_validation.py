"""A corrupt or hand-edited session.json never crashes startup (typed loading)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import startup_cleanup
import streamer

BASE = dict(file="/film.mkv", mode="transcode", offset=1.5, duration=60,
            device="TV", title="Film")


def load(tmp_path, monkeypatch, **overrides):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({**BASE, **overrides}), encoding="utf-8")
    monkeypatch.setattr(streamer, "SESSION_FILE", path)
    return streamer.load_session()


def test_valid_state_round_trips_unchanged(tmp_path, monkeypatch):
    state = load(tmp_path, monkeypatch, server_pid=42, burn_subs=True, speed=1.25)
    assert (state.server_pid, state.burn_subs, state.speed) == (42, True, 1.25)


@pytest.mark.parametrize("field", ["server_pid", "ffmpeg_pid", "caster_pid"])
@pytest.mark.parametrize("bad", [[], {}, "7", None, True, 1.5, 2.0 ** 70])
def test_bad_optional_fields_fall_back_to_defaults(tmp_path, monkeypatch, field, bad):
    state = load(tmp_path, monkeypatch, **{field: bad})
    assert state is not None
    assert getattr(state, field) == 0


@pytest.mark.parametrize("field", ["file", "mode", "offset", "duration", "device", "title"])
@pytest.mark.parametrize("bad", [None, [], {}, True, float("inf")])
def test_bad_required_fields_reject_the_file(tmp_path, monkeypatch, field, bad):
    path = tmp_path / "session.json"
    path.write_text(json.dumps({**BASE, field: bad}, allow_nan=True), encoding="utf-8")
    monkeypatch.setattr(streamer, "SESSION_FILE", path)
    assert streamer.load_session() is None


def test_startup_cleanup_survives_an_unhashable_server_pid(tmp_path, monkeypatch):
    load(tmp_path, monkeypatch, server_pid=[])
    with mock.patch.object(startup_cleanup.process_identity, "psutil", None), \
            mock.patch.object(startup_cleanup.platform, "system", return_value="Linux"):
        report = startup_cleanup.cleanup_before_window(
            keep_streaming=False, proc_root=tmp_path / "proc",
            temp_root=tmp_path / "tmp", grace=0)
    assert report is not None
