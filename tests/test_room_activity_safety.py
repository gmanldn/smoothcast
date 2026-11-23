"""Room activity security, status categories, replay and lifecycle (#332).

Only loopback server/pure model code: never starts GTK or touches receivers.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal  # noqa: E402
import portal_room  # noqa: E402
import room_activity  # noqa: E402


def test_actor_name_and_verified_title_are_carried_without_private_context():
    room = portal_room.PortalRoom()
    sam = room.join("Sam")
    room.remember({"q1": "Heat"})
    room.record(sam.id, "action", {
        "action": "queue_remove", "id": "q1", "outcome": "accepted",
        "title": "C:\\Users\\SAM\\PRIVATE.mkv", "url": "https://secret.example",
        "ip": "192.168.0.55", "pin": "123456", "token": "secret", "payload": ["secret"],
        "source": "/home/sam/private.mp4", "exception": "secret",
    }, command_id="command-1")
    event = room.snapshot(sam.id)["activity"][-1]
    assert event["data"] == {
        "name": "Sam", "action": "queue_remove", "outcome": "accepted", "title": "Heat",
    }
    encoded = json.dumps(event)
    for private in ("C:\\", "Users", "PRIVATE", "https://", "192.168.", "123456",
                    "secret", "/home/", "token", "exception"):
        assert private not in encoded
    assert event["actor"] == sam.id


def test_voting_actor_is_attributed_even_without_name_in_vote_payload():
    room = portal_room.PortalRoom()
    ana = room.join("Ana")
    room.remember({"id": "Interstellar"})
    room.vote(ana.id, "id", True)
    assert room.snapshot()["activity"][-1]["data"] == {
        "name": "Ana", "voted": True, "votes": 1, "title": "Interstellar",
    }


def test_user_controlled_title_cannot_inject_events_or_unsafe_paths():
    room = portal_room.PortalRoom()
    sam = room.join("Sam")
    room.record(sam.id, "action", {"title": "secret.mp4", "action": "seek",
                                    "outcome": "confirmed"})
    assert room.events[-1]["data"] == {
        "name": "Sam", "action": "seek", "outcome": "confirmed",
    }
    room.remember({"id": "https://example.com/private", "id2": "Face/Off"})
    room.record(sam.id, "action", {"action": "play_pause", "id": "id"})
    room.record(sam.id, "action", {"action": "play_pause", "id": "id2"})
    assert "title" not in room.events[-1]["data"]
    assert "title" not in room.events[-2]["data"]


def test_poisoned_activity_types_and_extreme_payloads_cannot_escape_schema():
    for poisoned in (["accepted"], {"field": "accepted"}, 123, None):
        fields = room_activity.event_fields(
            "action", {"action": poisoned, "outcome": poisoned, "reason": poisoned,
                       "private": "C:\\victim\\secret", "title": "/home/secret"},
            actor_name="Sam", known_title="Heat")
        assert fields == {"name": "Sam", "action": "control", "outcome": "accepted",
                          "title": "Heat"}
    assert room_activity.reason_for_status(403) == "permission"
    assert room_activity.reason_for_status(409) == "conflict"
    assert room_activity.reason_for_status(429) == "busy"
    assert room_activity.reason_for_status(404) == "unavailable"
    assert room_activity.reason_for_status(503) == "error"


def test_replayed_receipt_has_only_one_activity_and_bounded_keys():
    clock = [100.0]
    room = portal_room.PortalRoom(clock=lambda: clock[0])
    sam = room.join("Sam")
    room.record(sam.id, "action", {"action": "seek", "outcome": "accepted"},
                command_id="x", now=clock[0])
    before = room.seq
    room.record(sam.id, "action", {"action": "seek", "outcome": "confirmed"},
                command_id="x", now=clock[0])
    assert room.seq == before and len(room._activity_keys) == 1
    for index in range(room_activity.MAX_COMMAND_KEYS + 9):
        room.record(sam.id, "action", {"action": "volume"},
                    command_id=f"cmd-{index}", now=clock[0])
    assert len(room._activity_keys) == room_activity.MAX_COMMAND_KEYS
    assert len(room.events) == portal_room.MAX_EVENTS
    assert len(room.snapshot()["activity"]) == 20
    clock[0] += 121
    room.record(sam.id, "action", {"action": "seek"}, command_id="x", now=clock[0])
    assert room.seq == before + room_activity.MAX_COMMAND_KEYS + 10
    assert len(room._activity_keys) == 1


def test_room_snapshot_detaches_log_and_prunes_old_entries():
    wall = [100_000.0]
    room = portal_room.PortalRoom(wall_clock=lambda: wall[0])
    room.join("Sam")
    snap = room.snapshot()
    snap["activity"][0]["data"]["name"] = "ATTACK"
    assert room.snapshot()["activity"][0]["data"]["name"] == "Sam"
    wall[0] += room_activity.MAX_EVENT_AGE + 1
    assert room.snapshot()["activity"] == []
    assert room.seq > 0


def test_revoke_all_purges_activity_and_titles_without_stopping_playback():
    commands = []
    server = portal._PortalHTTPServer(("127.0.0.1", 0), "234567",
                                       lambda action, payload: commands.append(action))
    try:
        token, _csrf, sam = server.create_session("Sam")
        server.room.remember({"id": "Secret favourite"})
        server.room.record(sam.id, "action", {
            "action": "queue_remove", "id": "id"})
        seq = server.room.seq
        assert server.room.snapshot()["activity"]
        assert server.revoke_all() != "234567"
        assert server.room.events == type(server.room.events)(maxlen=portal_room.MAX_EVENTS)
        assert server.room.titles == {}
        assert server.room.votes == {}
        assert server.room.seq > seq
        assert server.session_participant(token) is None
        assert server.room.participants == {} and server.room._dormant == {}
        # An in-flight HTTP reply from the revoked guest cannot resurrect activity.
        server.room.record(sam.id, "action", {"action": "seek",
                                              "title": "Private film"},
                           command_id="late-reply")
        assert not server.room.events
        token2, _csrf2, _new = server.create_session("New guest")
        fresh = json.dumps(server.room.snapshot())
        assert "Sam" not in fresh and "Secret favourite" not in fresh
        assert server.session_participant(token2) is not None
        assert commands == []  # no media dispatch on PIN rotation
    finally:
        server.server_close()


def test_queue_receipt_is_not_double_logged_and_failure_is_categorised():
    dispatched = []

    def dispatch(action, payload):
        dispatched.append((action, payload))
        if action == "queue_remove":
            raise portal.PortalRequestError(403, "Cannot use /private/path or PIN 123456")
        return "Queue updated"

    server = portal._PortalHTTPServer(("127.0.0.1", 0), "234567", dispatch)
    try:
        _token, _csrf, sam = server.create_session("Sam")
        command = {"action": "queue_clear", "queue_command_id": "test-01",
                   "queue_revision": 0}
        assert server.execute_queue_command(sam.id, command)[0] == 202
        seq = server.room.seq
        assert server.execute_queue_command(sam.id, command)[0] == 202
        assert server.room.seq == seq
        event = server.room.events[-1]
        assert event["data"]["outcome"] == "accepted"
        assert len(dispatched) == 1

        bad = {"action": "queue_remove", "queue_command_id": "test-02",
               "queue_revision": 0, "id": "q1"}
        assert server.execute_queue_command(sam.id, bad)[0] == 403
        assert server.execute_queue_command(sam.id, bad)[0] == 403
        event = server.room.events[-1]
        assert event["data"] == {
            "name": "Sam", "action": "queue_remove",
            "outcome": "rejected", "reason": "permission",
        }
        assert "/private/path" not in json.dumps(server.room.snapshot())
        assert "123456" not in json.dumps(server.room.snapshot())
        assert len(dispatched) == 2
    finally:
        server.server_close()


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
def test_activity_receipt_copy_indicates_uncertain_and_rejected_states():
    line = next(line for line in portal._HTML.splitlines()
                if line.startswith("function describe(event){"))
    program = line + "\n" + (
        "const base={type:'action',data:{name:'Sam',action:'play_pause'}};"
        "for(const status of ['accepted','rejected','uncertain','confirmed'])"
        "console.log(describe({...base,data:{...base.data,outcome:status}}));"
    )
    output = subprocess.run(["node", "-e", program], capture_output=True,
                            text=True, check=True, timeout=8).stdout.splitlines()
    assert "confirmation pending" in output[0]
    assert "request refused" in output[1]
    assert "confirmation unavailable" in output[2]
    assert "confirmed" in output[3]
