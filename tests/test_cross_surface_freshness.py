"""Deterministic desktop ⇄ web freshness mechanism (#629).

The timing bound lives in tests/perf/test_cross_surface_freshness.py. This
headless test proves the mechanism itself, with no sleeps: a desktop change
publishes a newer web snapshot, and a web action updates the desktop
authoritative state and is never read stale afterwards. Real loopback portal,
fake receiver, no GTK, no TV.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import freshness_benchmark as fb


def _room_with_client():
    room = fb.Room()
    room.start()
    return room, fb.Client(room.port, "Web Remote")


def test_desktop_change_publishes_a_newer_web_snapshot():
    room, client = _room_with_client()
    try:
        before = client.state()
        room.desktop_act("volume", {"value": 33})
        after = client.state()
        assert after["volume"] == 33
        assert after["snapshot_version"] > before["snapshot_version"]
    finally:
        room.stop()


def test_web_action_updates_the_desktop_and_is_not_read_stale():
    room, client = _room_with_client()
    try:
        before = client.state()
        client.action({"action": "volume", "value": 17})
        assert room.view()["volume"] == 17
        after = client.state()
        assert after["volume"] == 17
        assert after["snapshot_version"] > before["snapshot_version"]
    finally:
        room.stop()


def test_stale_envelope_after_a_desktop_change_is_rejected():
    room, client = _room_with_client()
    try:
        state = client.state()
        stale_session, stale_revision = state["session_id"], state["revision"]
        room.desktop_act("volume", {"value": 21})   # rotates the fence generation
        with pytest.raises(RuntimeError):           # portal answers 409 conflict
            client.request("POST", "/api/action", {
                "client_id": "web", "command_id": "stale-1",
                "expected_session_id": stale_session, "expected_revision": stale_revision,
                "action": "volume", "payload": {"value": 60},
            })
        assert room.view()["volume"] == 21
    finally:
        room.stop()
