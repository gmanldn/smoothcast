"""Queue identity and shared-room queue actions for the LAN portal.

Kept out of ``cast_portal`` so the portal bridge remains a small concern; all
methods run on the GTK main thread because ``PortalQueueMixin`` is part of
``MainWindow``.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import stat

import portal


def portal_queue_id(path: str) -> str:
    """Stable opaque queue identity for web clients; paths never leave the host."""
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


class PortalQueueMixin:
    def _portal_queue_status(self) -> list[dict]:
        return [{
            "id": portal_queue_id(path),
            "title": pathlib.Path(path).name,
            "duration": self.queue_durations.get(path, 0.0),
        } for path in self.queue[:100]]

    def _portal_upload_path(self, payload: dict) -> pathlib.Path:
        portal_instance = getattr(self, "_portal", None)
        upload_root = getattr(getattr(portal_instance, "server", None), "uploads", None)
        root = getattr(upload_root, "root", None)
        if root is None:
            raise portal.PortalRequestError(503, "Upload storage is unavailable")
        path = pathlib.Path(payload.get("path", ""))
        try:
            info = path.lstat()
            path.relative_to(root)
        except (OSError, ValueError):
            raise portal.PortalRequestError(400, "Uploaded media is unavailable") from None
        if not stat.S_ISREG(info.st_mode) or not os.access(path, os.R_OK):
            raise portal.PortalRequestError(400, "Uploaded media is unavailable")
        return path

    def _portal_queue_index(self, item_id: object) -> int:
        if not isinstance(item_id, str):
            raise portal.PortalRequestError(400, "Queue item is missing")
        for index, path in enumerate(self.queue):
            if portal_queue_id(path) == item_id:
                return index
        raise portal.PortalRequestError(404, "That queue item is no longer here")

    def _portal_queue_action(self, operation: str, payload: dict) -> str | None:
        if operation == "queue_clear":
            self.clear_queue()
            return "Up Next cleared. Current playback is unchanged."
        if operation == "queue_add":
            path = self._portal_upload_path(payload)
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            self._enqueue([str(path)])
            return "Added to the queue."
        if operation == "queue_remove":
            self._remove_queue(self._portal_queue_index(payload.get("id")))
            return "Removed from the queue."
        if operation == "queue_move":
            item_id, position = payload.get("id"), payload.get("position")
            index = self._portal_queue_index(item_id)
            if type(position) is not int or not 0 <= position < len(self.queue):
                raise portal.PortalRequestError(400, "Queue position is outside the queue")
            selected = getattr(self, "selected_index", None)
            selected_path = (self.queue[selected]
                             if selected is not None and 0 <= selected < len(self.queue)
                             else None)
            path = self.queue.pop(index)
            self.queue.insert(position, path)
            self.selected_index = (self.queue.index(selected_path)
                                   if selected_path in self.queue else None)
            self._rebuild_queue()
            return "Queue order updated."
        if operation == "queue_play":
            index = self._portal_queue_index(payload.get("id"))
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            self._cast_path(pathlib.Path(self.queue[index]), 0.0)
            return "Playing now."
        if operation in {"next", "previous"}:
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            if self.now_playing is None:
                raise portal.PortalRequestError(409, "There is nothing playing")
            if operation == "next":
                self.on_next()
            else:
                self.on_prev()
            return "Playback command sent; the dashboard will refresh with receiver state."
        return None
