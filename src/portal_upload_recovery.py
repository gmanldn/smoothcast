"""Recover room uploads whose optional early Cast could not start."""
from __future__ import annotations

import time
import pathlib

import portal
import portal_uploads
from gi.repository import GLib

PORTAL_CAST_GRACE_SECONDS = 5.0


class PortalUploadRecoveryMixin:
    def _reconcile_portal_casts(self) -> None:
        """Drop early casts that never started so the finished file still casts."""
        casting = getattr(self, "_portal_cast_uploads", None)
        if not casting:
            return
        for upload_id, (path, _started) in list(casting.items()):
            if self.now_playing == path:
                casting.pop(upload_id, None)
        stale = portal_uploads.stale_early_casts(
            casting, now=time.monotonic(), busy=bool(self.busy),
            now_playing=self.now_playing, grace=PORTAL_CAST_GRACE_SECONDS)
        if not stale:
            return
        uploads = getattr(getattr(self, "_portal", None), "uploads", None)
        accepted = getattr(self, "_portal_accepted_uploads", None)
        for upload_id in stale:
            path = casting.pop(upload_id, (None, 0.0))[0]
            if accepted is not None:
                accepted.discard(upload_id)
            if uploads is None or path is None:
                continue
            uploads.mark_early_cast(upload_id, accepted=False)
            status = uploads.by_id(upload_id)
            retried = getattr(self, "_portal_cast_retried", None)
            if (status and status.get("complete") and retried is not None
                    and upload_id not in retried):
                retried.add(upload_id)
                GLib.idle_add(self._retry_portal_cast, upload_id, path)

    def _retry_portal_cast(self, upload_id: str, path: str) -> bool:
        if self.busy or getattr(self, "_closing", False):
            return False
        casting = getattr(self, "_portal_cast_uploads", None)
        if casting is None:
            return False
        # The idle callback may run after the host switched receivers, the
        # guest was revoked, or the portal was replaced. Recheck the original
        # server-side consent immediately before issuing any playback command.
        uploads = getattr(getattr(self, "_portal", None), "uploads", None)
        target = uploads.recovery_target(upload_id, path) if uploads is not None else None
        if not target:
            return False
        try:
            current = self._portal_upload_target()["target_id"]
        except portal.PortalRequestError:
            current = None
        if current != target:
            self.toast("Upload saved; playback retry cancelled because the confirmed receiver changed or is unavailable.")
            return False
        casting[upload_id] = (path, time.monotonic())
        accepted = getattr(self, "_portal_accepted_uploads", None)
        if accepted is not None:
            accepted.add(upload_id)
        try:
            reason = self._cast_path(pathlib.Path(path), 0)
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
