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


def test_queue_next_moves_item_to_front_without_touching_playback():
    host = QueueHost()
    host.queue.append("/private/three.mkv")
    host._portal_queue_status()
    item_id = portal_queue_id("/private/three.mkv")
    session, playing = host.session, host.now_playing

    result = host._portal_queue_action("queue_next", {
        "id": item_id, "queue_revision": host._portal_queue_revision})

    assert result == "Will play next."
    assert host.queue[0] == "/private/three.mkv"
    assert host.session is session and host.now_playing == playing


def test_queue_next_rejects_stale_revision():
    host = QueueHost()
    host._portal_queue_status()
    before = list(host.queue)
    with pytest.raises(portal.PortalRequestError) as error:
        host._portal_queue_action("queue_next", {
            "id": portal_queue_id(before[1]),
            "queue_revision": host._portal_queue_revision - 1})
    assert error.value.status == 409 and host.queue == before
