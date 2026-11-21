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
