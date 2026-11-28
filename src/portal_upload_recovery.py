"""Recover room uploads whose optional early Cast could not start."""
from __future__ import annotations

import time
import pathlib

import portal
import portal_uploads

PORTAL_CAST_GRACE_SECONDS = 5.0


def _glib():
    from gi.repository import GLib

    return GLib


class PortalUploadRecoveryController:
    """Composition replacement for PortalUploadRecoveryMixin (#691); GLib is injectable."""

    def __init__(self, window, glib=None) -> None:
        self.w = window
        self._glib = glib

    def reconcile(self) -> None:
        """Drop early casts that never started so the finished file still casts."""
        w = self.w
        casting = getattr(w, "_portal_cast_uploads", None)
        if not casting:
            return
        for upload_id, (path, _started) in list(casting.items()):
            if w.now_playing == path:
                casting.pop(upload_id, None)
        stale = portal_uploads.stale_early_casts(
            casting, now=time.monotonic(), busy=bool(w.busy),
            now_playing=w.now_playing, grace=PORTAL_CAST_GRACE_SECONDS)
        if not stale:
            return
        uploads = getattr(getattr(w, "_portal", None), "uploads", None)
        accepted = getattr(w, "_portal_accepted_uploads", None)
        for upload_id in stale:
            path = casting.pop(upload_id, (None, 0.0))[0]
            if accepted is not None:
                accepted.discard(upload_id)
            if uploads is None or path is None:
                continue
            uploads.mark_early_cast(upload_id, accepted=False)
            status = uploads.by_id(upload_id)
            retried = getattr(w, "_portal_cast_retried", None)
            if (status and status.get("complete") and retried is not None
                    and upload_id not in retried):
                retried.add(upload_id)
                (self._glib or _glib()).idle_add(self.retry, upload_id, path)

    def retry(self, upload_id: str, path: str) -> bool:
        w = self.w
        if w.busy or getattr(w, "_closing", False):
            return False
        casting = getattr(w, "_portal_cast_uploads", None)
        if casting is None:
            return False
        # The idle callback may run after the host switched receivers, the
        # guest was revoked, or the portal was replaced. Recheck the original
        # server-side consent immediately before issuing any playback command.
        uploads = getattr(getattr(w, "_portal", None), "uploads", None)
        target = uploads.recovery_target(upload_id, path) if uploads is not None else None
        if not target:
            return False
        try:
            current = w._portal_upload_target()["target_id"]
        except portal.PortalRequestError:
            current = None
        if current != target:
            w.toast("Upload saved; playback retry cancelled because the confirmed receiver changed or is unavailable.")
            return False
        casting[upload_id] = (path, time.monotonic())
        accepted = getattr(w, "_portal_accepted_uploads", None)
        if accepted is not None:
            accepted.add(upload_id)
        try:
            reason = w._cast_path(pathlib.Path(path), 0)
        except Exception:  # noqa: BLE001 - undo the dedupe bookkeeping then re-raise
            # A failed fallback must never leave a permanently deduped ID.
            casting.pop(upload_id, None)
            if accepted is not None:
                accepted.discard(upload_id)
            raise
        if reason is not None:
            casting.pop(upload_id, None)
            if accepted is not None:
                accepted.discard(upload_id)
        return False
