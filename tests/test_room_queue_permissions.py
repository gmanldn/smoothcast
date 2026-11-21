"""Permission table for the shared queue (#314/#323) over the real HTTP boundary.

Every queue endpoint must (a) require an authenticated session and a valid CSRF
token, (b) treat all authenticated participants identically, (c) lock out
revoked guests at once, and (d) never touch the active receiver.
"""
from __future__ import annotations

from test_room_conformance import RoomHarness, pytest

QUEUE_ACTIONS = ("queue_remove", "queue_move", "queue_clear")
TRANSPORT_ACTIONS = ("play_pause", "stop", "next", "previous")


def _edit(harness: RoomHarness, action: str, serial: int) -> dict:
    body: dict = {"action": action, "queue_revision": harness.queue_revision,
                  "queue_command_id": f"cmd-{action}-{serial}"}
    if action != "queue_clear":
        body["id"] = harness.queue[0]["id"]
    if action == "queue_move":
        body["position"] = 1
    return body


@pytest.fixture
def room():
    harness = RoomHarness(count=4)
    yield harness
    harness.close()


@pytest.mark.parametrize("action", QUEUE_ACTIONS + TRANSPORT_ACTIONS)
def test_unauthenticated_and_csrf_forged_actions_never_reach_dispatch(room, action):
    guest = room.login("Alice")
    body = _edit(room, action, 1)
    before = len(room.calls)
    status, _, _ = room.request("POST", "/api/action", body)
    assert status in (401, 403)
    status, _, _ = room.request("POST", "/api/action", body, cookie=guest.cookie)
    assert status == 403  # authenticated but no CSRF token
    status, _, _ = room.request("POST", "/api/action", body, cookie=guest.cookie,
                                csrf="forged")
    assert status == 403
    assert len(room.calls) == before


def test_queue_is_unreadable_without_a_session(room):
    status, _, _ = room.request("GET", "/api/status")
    assert status in (401, 403)


@pytest.mark.parametrize("action", QUEUE_ACTIONS)
def test_every_authenticated_participant_edits_identically(room, action):
    outcomes = []
    for index, name in enumerate(("Alice", "Bob", "Cara")):
        guest = room.login(name)
        guest.status()  # a browser loads the queue (and its item ids) first
        status, _, _ = guest.action(_edit(room, action, index))
        outcomes.append(status)
    # First edit commits; later ones are not forbidden, at worst a 404 (item
    # gone after clear/remove) -- never an authorisation failure.
    assert outcomes[0] in (200, 202)
    assert all(status not in (401, 403) for status in outcomes)


def test_queue_edits_never_dispatch_transport_commands(room):
    guest = room.login("Alice")
    guest.status()
    for index, action in enumerate(QUEUE_ACTIONS):
        guest.action(_edit(room, action, index))
    dispatched = {name for name, _ in room.calls}
    assert dispatched <= {"status", "queue_remove", "queue_move", "queue_clear"}


def test_revoked_guest_loses_read_and_edit_but_others_keep_both(room):
    alice, bob = room.login("Alice"), room.login("Bob")
    alice.status()
    assert room.server.revoke_participant(alice.participant_id) == 1
    assert alice.status()[0] in (401, 403)
    status, _, _ = alice.action(_edit(room, "queue_clear", 1))
    assert status in (401, 403)
    assert room.queue, "revoked guest must not mutate the queue"
    assert bob.status()[0] == 200
    status, _, _ = bob.action(_edit(room, "queue_clear", 2))
    assert status in (200, 202)
    assert room.queue == []


def test_end_guest_access_blocks_old_cookies_and_keeps_queue(room):
    alice = room.login("Alice")
    room.server.revoke_all()
    assert alice.status()[0] in (401, 403)
    status, _, _ = alice.action(_edit(room, "queue_clear", 1))
    assert status in (401, 403)
    assert len(room.queue) == 4
