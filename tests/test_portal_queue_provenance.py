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


def test_original_title_is_available_before_queue_row_creation():
    import pathlib
    host = Host()
    path = pathlib.Path("/private/opaque-upload.mp4")
    host.busy = False
    host._portal_upload_path = lambda payload: path
    def enqueue(paths):
        assert host._portal_queue_display_names[str(path)] == "Original film.mp4"
        host.queue.extend(paths)
    host._enqueue = enqueue
    host._portal_queue_action("queue_add", {"name": "Original film.mp4"})
    assert host._portal_queue_status()[0]["title"] == "Original film.mp4"


def test_verified_media_tags_and_original_name_share_title_projection(tmp_path):
    import queue_metadata
    path = tmp_path / "opaque.mp4"
    path.write_bytes(b"media")
    host = Host()
    host.queue.append(str(path))
    host._portal_note_display_name(path, "Original film.mp4")
    host._media_cache = {str(path): (queue_metadata.file_fingerprint(path),
                                    SimpleNamespace(title="Real title", artist="Artist"))}
    expected = "Artist — Real title"
    assert host._portal_queue_status()[0]["title"] == expected
    assert queue_metadata.media_title(path, host._media_cache[str(path)][1],
                                      "Original film.mp4") == expected
    assert queue_metadata.media_title(path, display_name="Original film.mp4") == "Original film.mp4"


def test_room_queue_projects_media_kind_and_fresh_duration(tmp_path):
    import queue_metadata
    path = tmp_path / "opaque.partial"
    path.write_bytes(b"media")
    host = Host()
    host.queue.append(str(path))
    host._portal_note_display_name(path, "Original film.mp4")
    row = host._portal_queue_status()[0]
    assert row["media_kind"] == "video" and row["duration"] == 0
    host._media_cache = {str(path): (queue_metadata.file_fingerprint(path),
                                    SimpleNamespace(has_video=False, is_audio_only=True,
                                                    duration=123.5))}
    host.queue_durations[str(path)] = 1.0
    row = host._portal_queue_status()[0]
    assert row["media_kind"] == "audio" and row["duration"] == 123.5


def test_home_queue_refreshes_on_duration_and_kind_changes():
    assert "item.contributor,item.media_kind,item.duration" in portal._HTML
    assert "mediaKindLabel(item.media_kind),item.duration?clock(item.duration)" in portal._HTML


def test_completed_guest_upload_joins_queue_during_cast_preparation():
    import pathlib
    host = Host()
    host.busy = True
    host.queue = ["/private/priority.mkv"]
    host.now_playing = None
    host.selected_index = 0
    host.session = object()
    active_session = host.session
    host._portal_upload_path = lambda payload: pathlib.Path("/private/background.mp4")
    payload = {"name": "Background film.mp4", "_portal_auth_key": "guest-b"}
    for _ in range(2):
        assert host._portal_queue_action("queue_add", payload) == "Added to the queue."
    assert host.queue == ["/private/priority.mkv", "/private/background.mp4"]
    assert host.busy and host.selected_index == 0 and host.session is active_session
    row = host._portal_queue_status()[1]
    assert row["title"] == "Background film.mp4" and row["contributor"] == "Sam"


def test_queue_acceptance_does_not_acknowledge_missing_item():
    import pathlib
    import pytest
    host = Host()
    host.busy = True
    host._portal_upload_path = lambda payload: pathlib.Path("/private/rejected.mp4")
    host._enqueue = lambda paths: None
    with pytest.raises(portal.PortalRequestError, match="could not accept"):
        host._portal_queue_action("queue_add", {"name": "Rejected.mp4"})
