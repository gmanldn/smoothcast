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
    def _portal_observe_queue(self) -> int:
        """Return the main-thread queue revision, advancing on any ordered change."""
        item_ids = tuple(portal_queue_id(path) for path in self.queue)
        if item_ids != getattr(self, "_portal_queue_snapshot", None):
            self._portal_queue_snapshot = item_ids
            self._portal_queue_revision = getattr(self, "_portal_queue_revision", 0) + 1
        return self._portal_queue_revision

    def _portal_queue_status(self) -> list[dict]:
        display_names = getattr(self, "_portal_queue_display_names", {})
        queued_paths = set(self.queue)
        for path in tuple(display_names):
            if path not in queued_paths:
                display_names.pop(path, None)
        rows = [{
            "id": portal_queue_id(path),
            "title": display_names.get(path, pathlib.Path(path).name),
            "duration": self.queue_durations.get(path, 0.0),
        } for path in self.queue[:100]]
        self._portal_observe_queue()
        return rows

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

    def _portal_library_path(self, key: object) -> pathlib.Path:
        """Resolve a search result to a readable file inside a shared library folder."""
        indexer = getattr(self, "_library_indexer", None)
        if indexer is None or indexer.entry(key) is None:
            raise portal.PortalRequestError(
                404, "That item isn't on this computer. Playing from other computers is coming soon.")
        path = indexer.resolve_path(key)
        if path is None:
            raise portal.PortalRequestError(404, "That file is no longer available.")
        return path

    def _portal_queue_index(self, item_id: object) -> int:
        if not isinstance(item_id, str):
            raise portal.PortalRequestError(400, "Queue item is missing")
        for index, path in enumerate(self.queue):
            if portal_queue_id(path) == item_id:
                return index
        raise portal.PortalRequestError(404, "That queue item is no longer here")

    def _portal_media_info(self, payload: dict) -> dict:
        """Resolve one opaque queue ID to a readable regular file for a room screen.

        Runs on the GTK thread so it sees the live queue. Only queued items can be
        streamed; the path is returned to the portal process internally and never
        reaches a client. The host can turn guest screens off entirely.
        """
        if not self.cfg.get("portal_screens", True):
            raise portal.PortalRequestError(
                403, "The host has turned off screens for this room")
        index = self._portal_queue_index(payload.get("id"))
        path = pathlib.Path(self.queue[index])
        try:
            info = path.stat()
        except OSError:
            raise portal.PortalRequestError(404, "That media is no longer available") from None
        if not stat.S_ISREG(info.st_mode) or not os.access(path, os.R_OK):
            raise portal.PortalRequestError(404, "That media is no longer available")
        display_names = getattr(self, "_portal_queue_display_names", {})
        return {"path": str(path),
                "title": display_names.get(str(path), path.name),
                "duration": self.queue_durations.get(str(path), 0.0)}

    def _portal_queue_action(self, operation: str, payload: dict) -> str | dict | None:
        if operation == "media_path":
            return self._portal_media_info(payload)
        if operation == "queue_clear":
            self._portal_check_queue_revision(payload)
            self.clear_queue()
            self._portal_observe_queue()
            return "Up Next cleared. Current playback is unchanged."
        if operation == "queue_add":
            path = self._portal_upload_path(payload)
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            self._enqueue([str(path)])
            name = payload.get("name")
            if isinstance(name, str) and name:
                display_names = getattr(self, "_portal_queue_display_names", None)
                if display_names is None:
                    display_names = {}
                    self._portal_queue_display_names = display_names
                display_names[str(path)] = name
            return "Added to the queue."
        if operation == "queue_remove":
            self._portal_check_queue_revision(payload)
            self._remove_queue(self._portal_queue_index(payload.get("id")))
            self._portal_observe_queue()
            return "Removed from the queue."
        if operation in {"queue_move", "queue_next"}:
            self._portal_check_queue_revision(payload)
            item_id, position = payload.get("id"), payload.get("position")
            index = self._portal_queue_index(item_id)
            if operation == "queue_next":
                current = self.now_playing or getattr(self, "_local_video_path", None)
                if self.queue[index] == current:
                    raise portal.PortalRequestError(409, "That item is already playing")
                if current in self.queue:
                    current_index = self.queue.index(current)
                    position = current_index + int(index > current_index)
                else:
                    position = 0
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
            self._portal_observe_queue()
            return "Queued next." if operation == "queue_next" else "Queue order updated."
        if operation == "queue_add_key":
            path = self._portal_library_path(payload.get("key"))
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            self._enqueue([str(path)])
            return "Added to the queue."
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

    def _portal_check_queue_revision(self, payload: dict) -> None:
        current = self._portal_observe_queue()
        expected = payload.get("queue_revision")
        if type(expected) is not int or expected != current:
            raise portal.PortalRequestError(409, "Up Next changed; refresh before editing")
