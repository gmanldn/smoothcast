"""Shared-room presence, votes and session expiry without HTTP or GTK."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
import portal_room


def test_names_are_unique_and_activity_is_bounded():
    room = portal_room.PortalRoom(now=100.0)
    sam = room.join("Sam", now=101.0)
    sam2 = room.join(" sam ", now=102.0)
    assert sam.name == "Sam" and sam2.name == "sam (2)"
    assert {person["name"] for person in room.snapshot(now=103.0)["participants"]} == {
        "Sam", "sam (2)"}
    for index in range(portal_room.MAX_EVENTS + 10):
        room.record(sam.id, "action", {"index": index}, now=104.0)
    assert len(room.snapshot(now=105.0)["activity"]) == 20
    assert len(sam.id) == 32


def test_participant_can_rename_self_without_changing_another_person():
    room = portal_room.PortalRoom(now=100.0)
    sam = room.join("Sam", now=100.0)
    alex = room.join("Alex", now=100.0)
    renamed = room.rename(sam.id, "New name", now=101.0)
    people = {person["id"]: person["name"]
              for person in room.snapshot(now=101.0)["participants"]}
    assert renamed.name == "New name"
    assert people == {sam.id: "New name", alex.id: "Alex"}


def test_renaming_collision_gets_a_unique_display_name():
    room = portal_room.PortalRoom(now=100.0)
    sam = room.join("Sam", now=100.0)
    room.join("Alex", now=100.0)
    assert room.rename(sam.id, "Alex", now=101.0).name == "Alex (2)"


def test_votes_are_per_person_and_pruned_with_the_queue():
    room = portal_room.PortalRoom(now=100.0)
    sam = room.join("Sam")
    alex = room.join("Alex")
    room.vote(sam.id, "one", True)
    room.vote(alex.id, "one", True)
    room.vote(sam.id, "two", True)
    snapshot = room.snapshot(sam.id)
    assert len(room.votes["one"]) == 2 and len(room.votes["two"]) == 1
    room.prune({"one"})
    assert set(room.votes) == {"one"}
    assert snapshot["me"]["id"] == sam.id
    room.vote(sam.id, "one", False)
    assert len(room.votes["one"]) == 1


def test_leaving_removes_presence_and_votes():
    room = portal_room.PortalRoom()
    sam = room.join("Sam")
    room.vote(sam.id, "one", True)
    room.leave(sam.id)
    assert room.snapshot()["participants"] == []
    assert room.votes["one"] == set()
    with pytest.raises(portal_room.RoomError) as error:
        room.touch(sam.id)
    assert error.value.status == 401


def test_room_limit_and_bad_vote_values():
    room = portal_room.PortalRoom()
    for index in range(portal_room.MAX_PARTICIPANTS):
        room.join(f"Person {index}")
    with pytest.raises(portal_room.RoomError) as error:
        room.join("Extra")
    assert error.value.status == 403
    with pytest.raises(portal_room.RoomError):
        room.vote(next(iter(room.participants)), "one", "yes")


def test_expired_portal_sessions_leave_the_room():
    now = [1000.0]
    server = portal._PortalHTTPServer(
        ("127.0.0.1", 0), "234567", lambda *_args: {},
        clock=lambda: now[0],
    )
    try:
        token, _csrf, participant = server.create_session("Sam")
        assert server.session_participant(token) == participant.id
        now[0] += portal.SESSION_SECONDS + 1
        assert server.session_csrf(token) is None
        assert server.room.snapshot()["participants"] == []
    finally:
        server.server_close()


def test_inactive_participant_leaves_roster_and_reconnect_keeps_name(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(portal.time, "time", lambda: now[0])
    server = portal._PortalHTTPServer(
        ("127.0.0.1", 0), "234567", lambda *_args: {}, clock=lambda: now[0],
    )
    try:
        token, _csrf, participant = server.create_session("Sam")
        now[0] += portal_room.ONLINE_SECONDS + 1
        server.service_actions()
        assert server.room.snapshot()["participants"] == []
        assert server.session_participant(token) == participant.id
        restored = server.room.snapshot(participant.id)["participants"]
        assert len(restored) == 1
        assert restored[0]["name"] == "Sam" and restored[0]["id"] == participant.id
    finally:
        server.server_close()


def test_dormant_presence_is_bounded_after_many_churned_clients():
    room = portal_room.PortalRoom(now=100.0)
    for index in range(portal_room.MAX_DORMANT_PARTICIPANTS + 5):
        room.join(f"Guest {index}", now=100.0 + index)
        room.expire_inactive(now=100.0 + index + portal_room.ONLINE_SECONDS + 1)
    assert room.snapshot()["participants"] == []
    assert len(room._dormant) == portal_room.MAX_DORMANT_PARTICIPANTS
