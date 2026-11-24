"""Queue contribution provenance follows accepted media, not client claims."""
from types import SimpleNamespace

from cast_portal_queue import PortalQueueMixin
import portal


class Host(PortalQueueMixin):
    def __init__(self):
        self.queue = []
        self.queue_durations = {}
        self._portal = SimpleNamespace(server=SimpleNamespace(
            session_display_name=lambda key: {"guest-a": "Alex", "guest-b": "Sam"}.get(key)
        ))

    def _enqueue(self, paths):
        self.queue.extend(path for path in paths if path not in self.queue)


def test_contributor_is_server_resolved_and_duplicate_does_not_reattribute():
    host = Host()
    a = {"_portal_auth_key": "guest-a", "contributor": "Impostor"}
    b = {"_portal_auth_key": "guest-b"}
    host._portal_enqueue_contributed("/private/film.mkv", host._portal_contributor(a), "upload")
    host._portal_enqueue_contributed("/private/film.mkv", host._portal_contributor(b), "library")
    host._portal_enqueue_contributed("/private/music.mp3", host._portal_contributor(b), "link")
    host.queue.reverse()
    rows = host._portal_queue_status()
    assert [(row["contributor"], row["source_kind"]) for row in rows] == [
        ("Sam", "link"), ("Alex", "upload"),
    ]
    assert "/private/" not in str(rows)
    assert "guest-a" not in str(rows)
    assert "Impostor" not in str(rows)


def test_removed_item_does_not_retain_old_contributor():
    host = Host()
    path = "/private/film.mkv"
    host._portal_enqueue_contributed(path, "Alex", "upload")
    host.queue.clear()
    host._portal_prune_queue_provenance()
    host._portal_enqueue_contributed(path, "Sam", "library")
    assert host._portal_queue_status()[0]["contributor"] == "Sam"
    host.queue.append("/private/older.mp4")
    assert "contributor" not in host._portal_queue_status()[1]


def test_queue_renderer_uses_text_and_refreshes_on_metadata_change():
    assert "item.voted,item.contributor,item.source_kind" in portal._HTML
    assert 'item.contributor?"Added by "+item.contributor' in portal._HTML
    assert "Contributor not recorded" in portal._HTML
