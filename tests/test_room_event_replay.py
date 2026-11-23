"""Offline SSE event ledger regression tests (#527)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from room_event_replay import RoomEventLedger

EPOCH = "0123456789abcdef"


def _id(frame: bytes) -> str:
    return frame.split(b"\n", 1)[0].split(b": ", 1)[1].decode("ascii")


def _document(frame: bytes) -> dict:
    return json.loads(frame.split(b"data: ", 1)[1].split(b"\n", 1)[0])


def test_epoch_and_monotonic_ids():
    stream = RoomEventLedger(epoch=EPOCH)
    first = stream.publish("sam", {"state": {"title": "One"}})
    second = stream.publish("sam", {"state": {"title": "Two"}})
    assert _id(first) == f"{EPOCH}:1"
    assert _id(second) == f"{EPOCH}:2"
    assert _document(first)["stream_epoch"] == EPOCH


def test_only_same_participant_can_replay():
    stream = RoomEventLedger(epoch=EPOCH)
    first = stream.publish("sam", {"state": {"title": "Sam 1"}})
    stream.publish("lee", {"state": {"title": "Lee 1"}})
    latest = stream.publish("sam", {"state": {"title": "Sam 2"}})
    assert stream.replay("sam", _id(first)) == ((latest,), None)
    assert stream.replay("lee", _id(first)) == ((), "gap")
    assert stream.replay("sam", _id(latest)) == ((), None)
    assert stream.replay("sam", None) == ((), None)


def test_invalid_restarted_and_unknown_ids():
    stream = RoomEventLedger(epoch=EPOCH)
    stream.publish("sam", {"ok": True})
    assert stream.replay("sam", "bad-header") == ((), "invalid")
    assert stream.replay("sam", "x" * 1000) == ((), "invalid")
    assert stream.replay("sam", "fedcba9876543210:1") == ((), "restarted")
    assert stream.replay("sam", f"{EPOCH}:500") == ((), "gap")


def test_global_cache_cap_and_eviction():
    stream = RoomEventLedger(epoch=EPOCH)
    old = stream.publish("sam", {"ok": True})
    for number in range(150):
        stream.publish("sam", {"number": number})
    assert len(stream._frames) == 128
    assert stream.replay("sam", _id(old)) == ((), "gap")


def test_oversize_is_delivered_but_not_cached():
    stream = RoomEventLedger(epoch=EPOCH)
    oversized = stream.publish("sam", {"text": "x" * 70000})
    assert len(oversized) > 65536
    assert stream.replay("sam", _id(oversized)) == ((), "gap")


def test_revocation_erases_history_and_resync_metadata_is_copy_only():
    stream = RoomEventLedger(epoch=EPOCH)
    payload = {"ok": True}
    first = stream.publish("sam", payload, resync="gap")
    second = stream.publish("lee", {"ok": True})
    assert _document(first)["stream_resync"] == "gap"
    assert payload == {"ok": True}
    stream.forget("sam")
    assert stream.replay("sam", _id(first)) == ((), "gap")
    assert stream.replay("lee", _id(second)) == ((), None)
    stream.clear()
    assert stream.replay("lee", _id(second)) == ((), "gap")
