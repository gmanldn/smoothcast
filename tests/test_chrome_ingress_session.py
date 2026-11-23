"""Headless, protocol-independent ingress state/epoch safety tests (#563)."""
from __future__ import annotations

from dataclasses import replace
import ast
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chrome_ingress_session import Event, Phase, SourceKind, Transition, advance

SID = "0123456789abcdef" * 2
SID2 = "fedcba9876543210" * 2


def ev(kind, *, epoch=3, sequence=5, source=SourceKind.SEEKABLE, **changes):
    return replace(Event(SID, epoch, sequence, kind, source, "req-5"), **changes)


def step(phase, event, *, session=SID, epoch=3, last=4):
    return advance(phase, event, current_session=session,
                   current_epoch=epoch, last_sequence=last)


@pytest.mark.parametrize(("prior", "kind", "expected"), [
    (Phase.IDLE, "auth_begin", Phase.AUTH),
    (Phase.AUTH, "auth_ok", Phase.NEGOTIATING),
    (Phase.NEGOTIATING, "negotiate", Phase.WAITING),
    (Phase.WAITING, "select_output", Phase.BUFFERING),
    (Phase.BUFFERING, "buffer_ready", Phase.BUFFERING),
    (Phase.BUFFERING, "receiver_playing", Phase.PLAYING),
    (Phase.PLAYING, "pause", Phase.PAUSED),
    (Phase.PAUSED, "resume", Phase.BUFFERING),
    (Phase.PAUSED, "receiver_playing", Phase.PLAYING),
    (Phase.PLAYING, "stop", Phase.STOPPING),
    (Phase.STOPPING, "stopped", Phase.ENDED),
    (Phase.WAITING, "fail", Phase.FAILED),
])
def test_valid_phase_transition_table(prior, kind, expected):
    assert step(prior, ev(kind)) == Transition(expected, True)


@pytest.mark.parametrize(("prior", "kind"), [
    (Phase.IDLE, "receiver_playing"),
    (Phase.AUTH, "select_output"),
    (Phase.NEGOTIATING, "receiver_playing"),
    (Phase.WAITING, "pause"),
    (Phase.PLAYING, "buffer_ready"),
    (Phase.STOPPING, "resume"),
    (Phase.STOPPING, "stop"),
])
def test_invalid_phase_transition_table(prior, kind):
    assert step(prior, ev(kind)) == Transition(prior, False, "illegal_transition")


def test_stale_session_epoch_and_sequence_rejected():
    assert step(Phase.PLAYING, ev("stop", session_id=SID2)).code == "session_mismatch"
    assert step(Phase.PLAYING, ev("stop", epoch=2)).code == "stale_epoch"
    assert step(Phase.PLAYING, ev("stop", epoch=4)).code == "stale_epoch"
    assert step(Phase.PLAYING, ev("stop", sequence=4)).code == "stale_sequence"
    assert step(Phase.PLAYING, ev("stop", sequence=3)).code == "stale_sequence"
    assert step(Phase.PLAYING, ev("stop"), session=SID2).code == "session_mismatch"


def test_only_confirmed_receiver_event_enters_playing():
    assert step(Phase.BUFFERING, ev("buffer_ready")).phase == Phase.BUFFERING
    assert step(Phase.BUFFERING, ev("receiver_playing")).phase == Phase.PLAYING
    assert step(Phase.PAUSED, ev("resume")).phase == Phase.BUFFERING
    assert step(Phase.WAITING, ev("receiver_playing")).accepted is False


def test_invalid_bool_negative_overflow_unknown_event_rejected():
    for event in (ev("other"), ev("stop", epoch=True), ev("stop", epoch=-1),
                  ev("stop", sequence=True), ev("stop", sequence=2**63),
                  ev("stop", request_id=""), ev("stop", request_id="bad space"),
                  ev("stop", session_id="wrong"), ev("stop", source_kind="live")):
        assert step(Phase.PLAYING, event).code == "invalid_event"
    assert step(Phase.PLAYING, ev("stop"), last=True).code == "invalid_event"
    assert step(Phase.PLAYING, ev("stop"), epoch=True).code == "invalid_event"
    with pytest.raises(ValueError):
        step("playing", ev("stop"))


def test_terminal_phase_cannot_revive():
    for phase in (Phase.ENDED, Phase.FAILED):
        for kind in ("auth_begin", "stop", "receiver_playing", "fail"):
            assert step(phase, ev(kind)) == Transition(phase, False, "terminal")


def test_unsupported_source_cannot_claim_playback():
    for kind, phase in (("select_output", Phase.WAITING),
                        ("buffer_ready", Phase.BUFFERING),
                        ("receiver_playing", Phase.BUFFERING),
                        ("resume", Phase.PAUSED)):
        assert step(phase, ev(kind, source=SourceKind.UNSUPPORTED)).code == "unsupported_source"
    assert step(Phase.WAITING, ev("stop", source=SourceKind.UNSUPPORTED)).phase == Phase.STOPPING


def test_imports_without_gtk_network_or_runtime_side_effects():
    src = Path(__file__).resolve().parents[1] / "src/chrome_ingress_session.py"
    modules = {n.module for n in ast.walk(ast.parse(src.read_text(encoding="utf-8")))
               if isinstance(n, ast.ImportFrom)}
    assert modules <= {"__future__", "dataclasses", "enum"}
