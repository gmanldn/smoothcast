"""Host-side resolution of an opaque queue ID to a streamable file (GTK owner)."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import portal
from cast_portal_queue import PortalQueueMixin, portal_queue_id
from gui_source import combined_source


class Host(PortalQueueMixin):
    def __init__(self, queue, cfg=None):
        self.queue = [str(path) for path in queue]
        self.queue_durations = {self.queue[0]: 61.0} if self.queue else {}
        self.cfg = cfg if cfg is not None else {}


def test_a_queued_regular_file_resolves_with_title_and_duration(tmp_path):
    media = tmp_path / "Film Night.mp4"
    media.write_bytes(b"x")
    host = Host([media])
    info = host._portal_queue_action("media_path", {"id": portal_queue_id(str(media))})
    assert info == {"path": str(media), "title": "Film Night.mp4", "duration": 61.0}
    host._portal_queue_display_names = {str(media): "Uploaded name.mp4"}
    assert host._portal_media_info({"id": portal_queue_id(str(media))})["title"] == \
        "Uploaded name.mp4"


def test_only_queued_items_can_be_streamed(tmp_path):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    other = tmp_path / "private.mp4"
    other.write_bytes(b"y")
    host = Host([media])
    with pytest.raises(portal.PortalRequestError) as error:
        host._portal_media_info({"id": portal_queue_id(str(other))})
    assert error.value.status == 404
    for bad in (None, 5, "", "../../etc/passwd"):
        with pytest.raises(portal.PortalRequestError):
            host._portal_media_info({"id": bad})


def test_missing_unreadable_and_non_regular_files_are_refused(tmp_path):
    gone = tmp_path / "gone.mp4"
    folder = tmp_path / "folder.mp4"
    folder.mkdir()
    for path in (gone, folder):
        host = Host([path])
        with pytest.raises(portal.PortalRequestError) as error:
            host._portal_media_info({"id": portal_queue_id(str(path))})
        assert error.value.status == 404
    locked = tmp_path / "locked.mp4"
    locked.write_bytes(b"x")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("running with permissions that ignore file modes")
        with pytest.raises(portal.PortalRequestError):
            Host([locked])._portal_media_info({"id": portal_queue_id(str(locked))})
    finally:
        locked.chmod(0o600)


def test_the_host_can_turn_screens_off(tmp_path):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    host = Host([media], {"portal_screens": False})
    with pytest.raises(portal.PortalRequestError) as error:
        host._portal_media_info({"id": portal_queue_id(str(media))})
    assert error.value.status == 403 and "turned off" in error.value.message


def test_desktop_wiring_for_screens_is_present():
    source = combined_source()
    assert '"portal_screens": True' in source               # on by default
    assert '"portal_screens"' in source.split("def _change_switch", 1)[1]
    assert "Let room browsers play the queue" in source
    assert "row.get(\"ready\")" in source                    # activity line
