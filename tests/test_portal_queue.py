"""Queue edit fencing on the GTK-owned portal queue seam."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import portal
from cast_portal_queue import PortalQueueMixin, portal_queue_id


class QueueHost(PortalQueueMixin):
    def __init__(self):
        self.queue = ["/private/one.mkv", "/private/two.mkv"]
        self.queue_durations = {}
        self.now_playing = "/private/one.mkv"
        self.session = object()
        self.busy = False
        self.selected_index = 0

    def clear_queue(self):
        self.queue.clear()
        self.selected_index = None

    def _remove_queue(self, index):
        self.queue.pop(index)

    def _rebuild_queue(self):
        pass


def test_stale_revision_rejects_queue_edits_before_mutation():
    host = QueueHost()
    host._portal_queue_status()
    item_id = portal_queue_id(host.queue[1])
    before = list(host.queue)

    with pytest.raises(portal.PortalRequestError) as error:
        host._portal_queue_action("queue_remove", {
            "id": item_id, "queue_revision": host._portal_queue_revision - 1,
        })

    assert error.value.status == 409
    assert host.queue == before


def test_clear_up_next_changes_revision_and_preserves_active_cast():
    host = QueueHost()
    host._portal_queue_status()
    old_revision = host._portal_queue_revision
    session = host.session

    result = host._portal_queue_action("queue_clear", {
        "queue_revision": old_revision,
    })

    assert result == "Up Next cleared. Current playback is unchanged."
    assert host.queue == []
    assert host.now_playing == "/private/one.mkv"
    assert host.session is session
    assert host._portal_queue_revision == old_revision + 1


def test_desktop_queue_changes_advance_revision_on_status_read():
    host = QueueHost()
    host._portal_queue_status()
    revision = host._portal_queue_revision

    host.queue.reverse()
    host._portal_queue_status()

    assert host._portal_queue_revision == revision + 1


def test_queue_next_rejects_stale_revision():
    host = QueueHost()
    host._portal_queue_status()
    before = list(host.queue)
    with pytest.raises(portal.PortalRequestError) as error:
        host._portal_queue_action("queue_next", {
            "id": portal_queue_id(before[1]),
            "queue_revision": host._portal_queue_revision - 1})
    assert error.value.status == 409 and host.queue == before


@pytest.mark.parametrize("target,expected", [
    ("/private/history.mkv", ["one", "history", "two", "three"]),
    ("/private/three.mkv", ["history", "one", "three", "two"]),
])
def test_queue_next_preserves_playback_and_selected_item(target, expected):
    host = QueueHost()
    host.queue = [f"/private/{stem}.mkv" for stem in ("history", "one", "two", "three")]
    host.selected_index = 2
    host.busy = True
    session = host.session
    revision = host._portal_observe_queue()

    assert host._portal_queue_action("queue_next", {
        "id": portal_queue_id(target), "queue_revision": revision,
    }) == "Queued next."

    assert [Path(path).stem for path in host.queue] == expected
    assert host.queue[host.selected_index] == "/private/two.mkv"
    assert host.now_playing == "/private/one.mkv"
    assert host.session is session
    assert host._portal_queue_revision == revision + 1
    from playback_state import next_media

    assert next_media(host.now_playing, host.queue, repeat_current=False, auto_next=True) == target


def test_queue_next_with_no_active_queue_item_moves_to_front():
    host = QueueHost()
    host.now_playing = "/private/unlisted.mkv"
    target = host.queue[-1]
    host._portal_queue_action("queue_next", {
        "id": portal_queue_id(target), "queue_revision": host._portal_observe_queue(),
    })
    assert host.queue[0] == target
    assert host.now_playing == "/private/unlisted.mkv"


def test_two_guests_see_the_same_queue_next_and_replay_is_idempotent():
    from test_room_conformance import RoomHarness

    host = QueueHost()
    host.queue.append("/private/three.mkv")

    class Room(RoomHarness):
        def dispatch(self, action, payload):
            self.calls.append((action, payload))
            if action == "status":
                return {"queue": host._portal_queue_status(),
                        "queue_revision": host._portal_observe_queue()}
            return host._portal_queue_action(action, payload)

    room = Room()
    try:
        alice, bob = room.login("Alice"), room.login("Bob")
        state = alice.status()[1]["state"]
        body = {"action": "queue_next", "id": state["queue"][2]["id"],
                "queue_revision": state["queue_revision"], "queue_command_id": "next-1"}
        assert alice.action(body)[0] == 202
        assert alice.action(body)[0] == 202
        assert bob.action({**body, "queue_command_id": "next-2"})[0] == 409
        a, b = (guest.status()[1]["state"] for guest in (alice, bob))
        assert a["queue"] == b["queue"]
        assert [item["title"] for item in b["queue"]] == ["one.mkv", "three.mkv", "two.mkv"]
        assert a["queue_revision"] == b["queue_revision"] == state["queue_revision"] + 1
        assert [action for action, _ in room.calls].count("queue_next") == 2
    finally:
        room.close()


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize("accept", [False, True])
def test_local_library_queue_add_preserves_receiver_and_reports_real_acceptance(busy, accept):
    host = QueueHost()
    host.busy = busy
    session, playing = host.session, host.now_playing
    path = "/shared/film.mp4"
    host._portal_library_path = lambda key: Path(path)
    host._portal_contributor = lambda payload: "Guest"

    def enqueue(paths):
        if accept:
            host.queue.extend(paths)

    host._enqueue = enqueue
    before = list(host.queue)
    for _ in range(2):
        if accept:
            assert host._portal_queue_action("queue_add_key", {"key": "opaque"}) == "Added to the queue."
        else:
            with pytest.raises(portal.PortalRequestError) as error:
                host._portal_queue_action("queue_add_key", {"key": "opaque"})
            assert error.value.status == 503
    assert host.queue == before + ([path] if accept else [])
    assert host.session is session and host.now_playing == playing
    if accept:
        assert host._portal_queue_provenance[path] == {
            "contributor": "Guest", "source_kind": "library",
        }


def test_active_upload_title_survives_clear_until_playback_ends():
    host = QueueHost()
    active, waiting = host.queue
    host._portal_note_display_name(active, "Original film.mp4")
    host._portal_note_display_name(waiting, "Waiting film.mp4")
    host._portal_record_contribution(active, "Guest", "upload")
    host.clear_queue()
    host._portal_queue_status()
    assert host._portal_queue_display_names == {active: "Original film.mp4"}
    assert host._portal_queue_provenance == {}
    host.now_playing = None
    host._portal_queue_status()
    assert host._portal_queue_display_names == {}
