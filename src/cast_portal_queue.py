"""Queue identity and shared-room queue actions for the LAN portal.

Kept out of ``cast_portal`` so the portal bridge remains a small concern; all
methods run on the GTK main thread because ``PortalQueueMixin`` is part of
``MainWindow``.
"""
from __future__ import annotations

import guest_messages
import hashlib
import os
import pathlib
import stat
import secrets

import portal
import portal_uploads
import queue_metadata


def portal_queue_id(path: str) -> str:
    """Stable opaque queue identity for web clients; paths never leave the host."""
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def _fetch_message(error: object, title: str) -> str:
    """User-presentable text for a failed copy (house_fetch errors are written for users)."""
    text = error.args[0] if getattr(error, "args", None) and isinstance(error.args[0], str) else ""
    return f"Couldn't copy “{title}”: {text}" if text else f"Couldn't copy “{title}”."


class PortalQueueMixin:
    def _portal_observe_queue(self) -> int:
        """Return the main-thread queue revision, advancing on any ordered change."""
        item_ids = tuple(portal_queue_id(path) for path in self.queue)
        if item_ids != getattr(self, "_portal_queue_snapshot", None):
            self._portal_queue_snapshot = item_ids
            self._portal_queue_revision = getattr(self, "_portal_queue_revision", 0) + 1
        return self._portal_queue_revision

    def _portal_prune_queue_provenance(self) -> None:
        queued_paths = set(self.queue)
        for attr in ("_portal_queue_display_names", "_portal_queue_provenance"):
            records = getattr(self, attr, {})
            for path in tuple(records):
                if path not in queued_paths:
                    records.pop(path, None)

    def _portal_contributor(self, payload: dict) -> str | None:
        server = getattr(getattr(self, "_portal", None), "server", None)
        lookup = getattr(server, "session_display_name", None)
        if callable(lookup):
            return lookup(payload.get("_portal_auth_key"))
        return None

    def _portal_note_display_name(self, path: object, name: object) -> None:
        """Keep the guest-supplied filename so the queue never shows the opaque upload id."""
        if not isinstance(name, str) or not name:
            return
        display_names = getattr(self, "_portal_queue_display_names", None)
        if display_names is None:
            display_names = {}
            self._portal_queue_display_names = display_names
        display_names[str(path)] = name

    def _portal_record_contribution(self, path: str, contributor: str | None,
                                    source: str) -> None:
        self.__dict__.setdefault("_portal_queue_provenance", {})[path] = {
            "contributor": contributor, "source_kind": source,
        }

    def _portal_enqueue_contributed(self, path: str, contributor: str | None,
                                    source: str) -> None:
        if path in self.queue:
            return
        self._enqueue([path])
        if path in self.queue:
            self._portal_record_contribution(path, contributor, source)

    def _portal_queue_status(self) -> list[dict]:
        self._portal_prune_queue_provenance()
        display_names = getattr(self, "_portal_queue_display_names", {})
        provenance = getattr(self, "_portal_queue_provenance", {})
        rows = []
        cache = getattr(self, "_media_cache", {})
        for path in self.queue[:100]:
            name = display_names.get(path)
            media = queue_metadata.cached_media(cache, path)
            suffix = pathlib.Path(name or path).suffix.lower()
            if media is not None and getattr(media, "has_video", False):
                kind = "video"
            elif media is not None and getattr(media, "is_audio_only", False):
                kind = "audio"
            elif suffix in portal_uploads.VIDEO_SUFFIXES:
                kind = "video"
            elif suffix in portal_uploads.AUDIO_SUFFIXES:
                kind = "audio"
            else:
                kind = ""
            rows.append({
                "id": portal_queue_id(path),
                "title": queue_metadata.media_title(path, media, name),
                "duration": getattr(media, "duration", 0.0) or self.queue_durations.get(path, 0.0),
                "media_kind": kind,
                **provenance.get(path, {}),
            })
        self._portal_observe_queue()
        return rows

    def _portal_upload_path(self, payload: dict) -> pathlib.Path:
        portal_instance = getattr(self, "_portal", None)
        upload_root = getattr(getattr(portal_instance, "server", None), "uploads", None)
        root = getattr(upload_root, "root", None)
        if root is None:
            raise portal.PortalRequestError(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
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

    def _portal_run_async(self, work, done, failed) -> None:
        from cast_widgets import Async
        Async.run(work, done=done, failed=failed, domain="media",
                  valid=lambda: not getattr(self, "_closing", False))

    def _portal_copy_status(self) -> list[dict]:
        """Bounded, guest-safe transfer receipts; never publish keys or paths."""
        return [dict(row) for row in getattr(self, "_portal_copy_receipts", {}).values()]

    def _portal_fetch_remote(self, key: object, contributor: str | None = None,
                             session_key: object = None) -> str:
        """Copy a file from another computer into the cache, then queue the copy."""
        mesh = getattr(self, "_mesh_library", None)
        source = mesh.remote_source(key) if mesh is not None and isinstance(key, str) else None
        if source is None:
            raise portal.PortalRequestError(
                404, "That item isn't available right now; its computer may be asleep.")
        pending = self.__dict__.setdefault("_portal_fetching", set())
        if key in pending:
            return f"Already fetching “{source['title']}”."
        if len(pending) >= 8:
            raise portal.PortalRequestError(429, "Too many library copies are in progress. Try again shortly.")
        pending.add(key)
        title, where = source["title"], source["name"]
        receipts = self.__dict__.setdefault("_portal_copy_receipts", {})
        while len(receipts) >= 24:
            oldest = next((ident for ident, row in receipts.items()
                           if row["stage"] != "copying"), None)
            if oldest is None:
                break
            receipts.pop(oldest)
        ident = secrets.token_hex(12)
        receipt = receipts[ident] = {
            "id": ident, "title": title, "origin": where,
            "contributor": contributor, "stage": "copying",
        }
        server = getattr(getattr(self, "_portal", None), "server", None)
        keep = set(self.queue)

        def cancelled():
            if getattr(self, "_closing", False):
                return True
            if session_key is None:
                return False
            current = getattr(getattr(self, "_portal", None), "server", None)
            return current is not server or server is None or not server.session_key_active(session_key)

        def work():
            return mesh.fetch_remote(key, source, cancelled=cancelled, keep=keep)

        def done(path):
            pending.discard(key)
            if cancelled():
                receipt["stage"] = "cancelled"
                return
            try:
                self._portal_queue_display_names = getattr(self, "_portal_queue_display_names", {})
                self._portal_queue_display_names[str(path)] = title
                self._portal_enqueue_contributed(str(path), contributor, "library")
                receipt["stage"] = "ready" if str(path) in self.queue else "failed"
            except Exception:
                receipt["stage"] = "uncertain"
                self.toast("Library copy finished but queue acceptance could not be confirmed.", error=True)

        def failed(error):
            pending.discard(key)
            receipt["stage"] = "cancelled" if cancelled() else "failed"
            if receipt["stage"] == "failed":
                self.toast(_fetch_message(error, title), error=True)

        try:
            self._portal_run_async(work, done, failed)
        except Exception:
            pending.discard(key)
            receipt["stage"] = "failed"
            raise
        return f"Copying “{title}” from {where}; it joins Up Next when ready."

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
                "title": queue_metadata.display_title(path, getattr(self, "_media_cache", {}),
                                                      display_names.get(str(path))),
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
            # Queue-only contributions do not own or mutate the receiver.
            # Accept them while cast preparation is in flight.
            source = "link" if payload.get("_portal_source") == "link" else "upload"
            if str(path) not in self.queue:
                self._portal_note_display_name(path, payload.get("name"))
            self._portal_enqueue_contributed(str(path), self._portal_contributor(payload), source)
            if str(path) not in self.queue:
                raise portal.PortalRequestError(503, "The room could not accept this media. Retry shortly.")
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
            try:
                path = self._portal_library_path(payload.get("key"))
            except portal.PortalRequestError:
                return self._portal_fetch_remote(payload.get("key"), self._portal_contributor(payload),
                                                 payload.get("_portal_auth_key"))
            # Like validated uploads, a library queue edit does not own the receiver.
            self._portal_enqueue_contributed(str(path), self._portal_contributor(payload), "library")
            if str(path) not in self.queue:
                raise portal.PortalRequestError(503, "The room could not accept this media. Retry shortly.")
            return "Added to the queue."
        if operation == "queue_play":
            index = self._portal_queue_index(payload.get("id"))
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            reason = self._cast_path(pathlib.Path(self.queue[index]), 0.0)
            if reason is not None:
                raise portal.PortalRequestError(409, reason)
            return "Playback requested; waiting for the room receiver."
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
