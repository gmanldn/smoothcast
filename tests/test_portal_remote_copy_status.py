"""Remote copy receipts are separate from queue membership and fence revoked sessions."""
from types import SimpleNamespace

from cast_portal_queue import PortalQueueMixin


class Host(PortalQueueMixin):
    def __init__(self):
        self.queue = []
        self.queue_durations = {}
        self.active = True
        self._portal = SimpleNamespace(server=SimpleNamespace(
            session_key_active=lambda key: self.active,
        ))
        self._mesh_library = SimpleNamespace(
            remote_source=lambda key: {"title": "Film", "name": "Peer"},
            fetch_remote=lambda *args, **kwargs: "/private/film.mkv",
        )

    def _portal_run_async(self, work, done, failed):
        self.work, self.done, self.failed = work, done, failed

    def _enqueue(self, paths):
        self.queue.extend(paths)

    def toast(self, *args, **kwargs):
        pass


def test_copy_receipt_is_not_a_queue_item_until_delivery():
    host = Host()
    host._portal_fetch_remote("secret-content-key", "Alex", "secret-session-key")
    assert not host.queue
    row = host._portal_copy_status()[0]
    assert row["stage"] == "copying"
    assert "secret" not in str(row)
    assert "private" not in str(row)
    host.done(host.work())
    assert host._portal_copy_status()[0]["stage"] == "ready"
    assert host._portal_queue_status()[0]["contributor"] == "Alex"


def test_revoked_session_cannot_deliver_completed_copy():
    host = Host()
    host._portal_fetch_remote("key", "Alex", "session")
    host.active = False
    host.done("/private/film.mkv")
    assert not host.queue
    assert host._portal_copy_status()[0]["stage"] == "cancelled"


def test_copy_failure_is_reported_without_private_exception():
    host = Host()
    host._portal_fetch_remote("key", "Alex", "session")
    host.failed(RuntimeError("/private/secret"))
    assert not host.queue
    assert host._portal_copy_status()[0]["stage"] == "failed"
    assert "secret" not in str(host._portal_copy_status())
