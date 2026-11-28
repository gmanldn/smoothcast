"""Recovery must not send guest media to a different receiver (#572)."""
from pathlib import Path
import ast
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def method(filename, name, namespace):
    source = Path(__file__).resolve().parents[1] / "src" / filename
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


class PortalRequestError(Exception):
    pass


recovery_target = method("portal_uploads.py", "recovery_target", {})

def retry(window, upload_id, path):
    import portal_upload_recovery
    original = portal_upload_recovery.portal.PortalRequestError
    portal_upload_recovery.portal.PortalRequestError = PortalRequestError
    try:
        return portal_upload_recovery.PortalUploadRecoveryController(window).retry(upload_id, path)
    finally:
        portal_upload_recovery.portal.PortalRequestError = original


@pytest.mark.parametrize("change", [
    {"cancelled": True}, {"queue_only": True}, {"dispatch_pending": True},
    {"dispatch_queue_only": True}, {"directory_synced": False},
    {"complete_path": None}, {"complete_path": Path("different.mp4")},
    {"cast_target": None},
])
def test_recovery_consent_rejects_stale_or_unsafe_upload(change):
    upload = dict(cancelled=False, queue_only=False, dispatch_pending=False,
                  dispatch_queue_only=False, directory_synced=True,
                  complete_path=Path("film.mp4"), cast_target="confirmed")
    upload.update(change)
    manager = SimpleNamespace(_lock=threading.RLock(),
                              _uploads={"id": SimpleNamespace(**upload)})
    assert recovery_target(manager, "id", "film.mp4") is None
    assert recovery_target(manager, "missing", "film.mp4") is None


@pytest.mark.parametrize("current", ["confirmed", "changed", None])
def test_delayed_retry_revalidates_original_receiver(current):
    uploads = Mock()
    uploads.recovery_target.return_value = "confirmed"
    window = SimpleNamespace(
        busy=False, _closing=False, _portal=SimpleNamespace(uploads=uploads),
        _portal_cast_uploads={}, _portal_accepted_uploads=set(),
        _portal_upload_target=Mock(), _cast_path=Mock(return_value=None), toast=Mock(),
    )
    if current is None:
        window._portal_upload_target.side_effect = PortalRequestError()
    else:
        window._portal_upload_target.return_value = {"target_id": current}
    assert retry(window, "id", "film.mp4") is False
    uploads.recovery_target.assert_called_once_with("id", "film.mp4")
    if current == "confirmed":
        window._cast_path.assert_called_once_with(Path("film.mp4"), 0)
        assert "id" in window._portal_accepted_uploads
    else:
        window._cast_path.assert_not_called()
        assert not window._portal_accepted_uploads
        assert not window._portal_cast_uploads
        window.toast.assert_called_once()
