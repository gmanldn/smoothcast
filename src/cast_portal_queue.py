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
import secrets
import stat

import settings
import portal
import portal_uploads
from queue_component import QueueComponent
import queue_metadata
from room_events import store_for
import media_source


def portal_queue_id(path: str) -> str:
    """Stable opaque queue identity for web clients; paths never leave the host."""
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]


def _fetch_message(error: object, title: str) -> str:
    """User-presentable text for a failed copy (house_fetch errors are written for users)."""
    text = error.args[0] if getattr(error, "args", None) and isinstance(error.args[0], str) else ""
    return f"Couldn't copy “{title}”: {text}" if text else f"Couldn't copy “{title}”."


class PortalQueueController:
    """Composition replacement for PortalQueueMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _portal_observe_queue(self) -> int:
        """Return the main-thread queue revision, advancing on any ordered change."""
        w = self.w
        item_ids = tuple(portal_queue_id(path) for path in w.queue)
        w._portal_queue_snapshot, w._portal_queue_revision = QueueComponent.advance_revision(
            getattr(w, "_portal_queue_snapshot", None),
            getattr(w, "_portal_queue_revision", 0), item_ids)
        return w._portal_queue_revision

    def _portal_prune_queue_provenance(self) -> None:
        w = self.w
        queued_paths = set(w.queue)
        active = getattr(w, "now_playing", None)
        # The active item keeps its display name until playback ends.
        QueueComponent.prune_records(getattr(w, "_portal_queue_display_names", {}), queued_paths, active)
        QueueComponent.prune_records(getattr(w, "_portal_queue_provenance", {}), queued_paths)

    def _portal_contributor(self, payload: dict) -> str | None:
        w = self.w
        server = getattr(getattr(w, "_portal", None), "server", None)
        lookup = getattr(server, "session_display_name", None)
        if callable(lookup):
            return lookup(payload.get("_portal_auth_key"))
        return None

    def _portal_note_display_name(self, path: object, name: object) -> None:
        """Keep the guest-supplied filename so the queue never shows the opaque upload id."""
        w = self.w
        if not isinstance(name, str) or not name:
            return
        display_names = getattr(w, "_portal_queue_display_names", None)
        if display_names is None:
            display_names = {}
            w._portal_queue_display_names = display_names
        display_names[str(path)] = name

    def _portal_record_contribution(self, path: str, contributor: str | None,
                                    source: str) -> None:
        w = self.w
        w.__dict__.setdefault("_portal_queue_provenance", {})[path] = {
            "contributor": contributor, "source_kind": source,
        }

    def _portal_enqueue_contributed(self, path: str, contributor: str | None,
                                    source: str) -> None:
        w = self.w
        if path in w.queue:
            return
        w._enqueue([path])
        if path in w.queue:
            w._portal_record_contribution(path, contributor, source)

    def _portal_queue_status(self) -> list[dict]:
        w = self.w
        w._portal_prune_queue_provenance()
        display_names = getattr(w, "_portal_queue_display_names", {})
        provenance = getattr(w, "_portal_queue_provenance", {})
        rows = []
        cache = getattr(w, "_media_cache", {})
        for path in w.queue[:100]:
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
                "duration": getattr(media, "duration", 0.0) or w.queue_durations.get(path, 0.0),
                "media_kind": kind,
                **provenance.get(path, {}),
            })
        w._portal_observe_queue()
        return rows

    def _portal_upload_path(self, payload: dict) -> pathlib.Path:
        w = self.w
        portal_instance = getattr(w, "_portal", None)
        upload_root = getattr(getattr(portal_instance, "server", None), "uploads", None)
        root = getattr(upload_root, "root", None)
        if root is None:
            raise portal.PortalRequestError(503, guest_messages.UPLOAD_STORAGE_UNAVAILABLE)
        try:
            path = media_source.resolve_under(root, payload.get("path", ""))
        except media_source.SourceError:
            raise portal.PortalRequestError(400, "Uploaded media is unavailable") from None
        return path

    def _portal_library_path(self, key: object) -> pathlib.Path:
        """Resolve a search result to a readable file inside a shared library folder."""
        w = self.w
        indexer = getattr(w, "_library_indexer", None)
        if indexer is None or indexer.entry(key) is None:
            raise portal.PortalRequestError(
                404, "That item isn't on this computer. Playing from other computers is coming soon.")
        path = indexer.resolve_path(key)
        if path is None:
            raise portal.PortalRequestError(404, "That file is no longer available.")
        try:
            return media_source.library_source(indexer.shared_roots(), path)
        except media_source.SourceError:
            raise portal.PortalRequestError(404, "That file is no longer available.") from None

    def _portal_run_async(self, work, done, failed) -> None:
        w = self.w
        from cast_widgets import Async
        Async.run(work, done=done, failed=failed, domain="media",
                  valid=lambda: not getattr(w, "_closing", False))

    def _portal_copy_status(self) -> list[dict]:
        """Bounded, guest-safe transfer receipts; never publish keys or paths."""
        w = self.w
        return [dict(row) for row in getattr(w, "_portal_copy_receipts", {}).values()]

    def _portal_fetch_remote(self, key: object, contributor: str | None = None,
                             session_key: object = None) -> str:
        """Copy a file from another computer into the cache, then queue the copy."""
        w = self.w
        mesh = getattr(w, "_mesh_library", None)
        source = mesh.remote_source(key) if mesh is not None and isinstance(key, str) else None
        if source is None:
            raise portal.PortalRequestError(
                404, "That item isn't available right now; its computer may be asleep.")
        pending = w.__dict__.setdefault("_portal_fetching", set())
        if key in pending:
            return f"Already fetching “{source['title']}”."
        if len(pending) >= 8:
            raise portal.PortalRequestError(429, "Too many library copies are in progress. Try again shortly.")
        pending.add(key)
        title, where = source["title"], source["name"]
        receipts = w.__dict__.setdefault("_portal_copy_receipts", {})
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
        server = getattr(getattr(w, "_portal", None), "server", None)
        keep = set(w.queue)

        def cancelled():
            if getattr(w, "_closing", False):
                return True
            if session_key is None:
                return False
            current = getattr(getattr(w, "_portal", None), "server", None)
            return current is not server or server is None or not server.session_key_active(session_key)

        def work():
            return mesh.fetch_remote(key, source, cancelled=cancelled, keep=keep)

        def done(path):
            pending.discard(key)
            if cancelled():
                receipt["stage"] = "cancelled"
                return
            try:
                w._portal_queue_display_names = getattr(w, "_portal_queue_display_names", {})
                w._portal_queue_display_names[str(path)] = title
                w._portal_enqueue_contributed(str(path), contributor, "library")
                receipt["stage"] = "ready" if str(path) in w.queue else "failed"
            except Exception:  # noqa: BLE001 - queue acceptance unconfirmed is reported as uncertain
                receipt["stage"] = "uncertain"
                w.toast("Library copy finished but queue acceptance could not be confirmed.", error=True)

        def failed(error):
            pending.discard(key)
            receipt["stage"] = "cancelled" if cancelled() else "failed"
            if receipt["stage"] == "failed":
                w.toast(_fetch_message(error, title), error=True)

        try:
            w._portal_run_async(work, done, failed)
        except Exception:  # noqa: BLE001 - mark the fetch failed then re-raise
            pending.discard(key)
            receipt["stage"] = "failed"
            raise
        return f"Copying “{title}” from {where}; it joins Up Next when ready."

    def _portal_queue_index(self, item_id: object) -> int:
        w = self.w
        if not isinstance(item_id, str):
            raise portal.PortalRequestError(400, "Queue item is missing")
        for index, path in enumerate(w.queue):
            if portal_queue_id(path) == item_id:
                return index
        raise portal.PortalRequestError(404, "That queue item is no longer here")

    def _portal_media_info(self, payload: dict) -> dict:
        """Resolve one opaque queue ID to a readable regular file for a room screen.

        Runs on the GTK thread so it sees the live queue. Only queued items can be
        streamed; the path is returned to the portal process internally and never
        reaches a client. The host can turn guest screens off entirely.
        """
        w = self.w
        if not settings.PortalSettings.from_config(w.cfg).screens:
            raise portal.PortalRequestError(
                403, "The host has turned off screens for this room")
        index = w._portal_queue_index(payload.get("id"))
        path = pathlib.Path(w.queue[index])
        try:
            info = path.stat()
        except OSError:
            raise portal.PortalRequestError(404, "That media is no longer available") from None
        if not stat.S_ISREG(info.st_mode) or not os.access(path, os.R_OK):
            raise portal.PortalRequestError(404, "That media is no longer available")
        display_names = getattr(w, "_portal_queue_display_names", {})
        return {"path": str(path),
                "title": queue_metadata.display_title(path, getattr(w, "_media_cache", {}),
                                                      display_names.get(str(path))),
                "duration": w.queue_durations.get(str(path), 0.0)}

    def _portal_queue_action(self, operation: str, payload: dict) -> str | dict | None:
        w = self.w
        if operation == "media_path":
            return w._portal_media_info(payload)
        if operation == "queue_clear":
            w._portal_check_queue_revision(payload)
            w.clear_queue()
            w._portal_observe_queue()
            return "Up Next cleared. Current playback is unchanged."
        if operation == "queue_add":
            path = w._portal_upload_path(payload)
            # Queue-only contributions do not own or mutate the receiver.
            # Accept them while cast preparation is in flight.
            source = "link" if payload.get("_portal_source") == "link" else "upload"
            if str(path) not in w.queue:
                w._portal_note_display_name(path, payload.get("name"))
            w._portal_enqueue_contributed(str(path), w._portal_contributor(payload), source)
            if str(path) not in w.queue:
                raise portal.PortalRequestError(503, "The room could not accept this media. Retry shortly.")
            return "Added to the queue."
        if operation == "queue_remove":
            w._portal_check_queue_revision(payload)
            w._remove_queue(w._portal_queue_index(payload.get("id")))
            w._portal_observe_queue()
            return "Removed from the queue."
        if operation in {"queue_move", "queue_next"}:
            w._portal_check_queue_revision(payload)
            item_id, position = payload.get("id"), payload.get("position")
            index = w._portal_queue_index(item_id)
            if operation == "queue_next":
                current = w.now_playing or getattr(w, "_local_video_path", None)
                if w.queue[index] == current:
                    raise portal.PortalRequestError(409, "That item is already playing")
                if current in w.queue:
                    current_index = w.queue.index(current)
                    position = current_index + int(index > current_index)
                else:
                    position = 0
            if type(position) is not int or not 0 <= position < len(w.queue):
                raise portal.PortalRequestError(400, "Queue position is outside the queue")
            store = store_for(w)
            selected = getattr(w, "selected_index", None)
            selected_path = w.queue[selected] if selected is not None and 0 <= selected < len(w.queue) else None
            store.submit(secrets.token_hex(8), "move", index, position)
            w.selected_index = w.queue.index(selected_path) if selected_path in w.queue else None
            w._rebuild_queue()
            w._portal_observe_queue()
            return "Queued next." if operation == "queue_next" else "Queue order updated."
        if operation == "queue_add_key":
            try:
                path = w._portal_library_path(payload.get("key"))
            except portal.PortalRequestError:
                return w._portal_fetch_remote(payload.get("key"), w._portal_contributor(payload),
                                                 payload.get("_portal_auth_key"))
            # Like validated uploads, a library queue edit does not own the receiver.
            w._portal_enqueue_contributed(str(path), w._portal_contributor(payload), "library")
            if str(path) not in w.queue:
                raise portal.PortalRequestError(503, "The room could not accept this media. Retry shortly.")
            return "Added to the queue."
        if operation == "queue_play":
            index = w._portal_queue_index(payload.get("id"))
            if w.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            reason = w._cast_path(pathlib.Path(w.queue[index]), 0.0)
            if reason is not None:
                raise portal.PortalRequestError(409, reason)
            return "Playback requested; waiting for the room receiver."
        if operation in {"next", "previous"}:
            if w.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            if w.now_playing is None:
                raise portal.PortalRequestError(409, "There is nothing playing")
            if operation == "next":
                w.on_next()
            else:
                w.on_prev()
            return "Playback command sent; the dashboard will refresh with receiver state."
        return None

    def _portal_check_queue_revision(self, payload: dict) -> None:
        w = self.w
        current = w._portal_observe_queue()
        expected = payload.get("queue_revision")
        if type(expected) is not int or expected != current:
            raise portal.PortalRequestError(409, "Up Next changed; refresh before editing")

    @classmethod
    def install(cls, window) -> "PortalQueueController":
        """Bind every queue method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in PORTAL_QUEUE_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


PORTAL_QUEUE_METHODS = ('_portal_observe_queue', '_portal_prune_queue_provenance', '_portal_contributor', '_portal_note_display_name', '_portal_record_contribution', '_portal_enqueue_contributed', '_portal_queue_status', '_portal_upload_path', '_portal_library_path', '_portal_run_async', '_portal_copy_status', '_portal_fetch_remote', '_portal_queue_index', '_portal_media_info', '_portal_queue_action', '_portal_check_queue_revision')


class PortalQueueMixin:
    """Headless-host adapter (tests, tools): delegates to ``PortalQueueController``.

    ``MainWindow`` no longer inherits this; it calls ``PortalQueueController.install``.
    """


def _delegate(name: str):
    def method(self, *args, **kwargs):
        return getattr(PortalQueueController(self), name)(*args, **kwargs)
    method.__name__ = name
    return method


for _name in PORTAL_QUEUE_METHODS:
    setattr(PortalQueueMixin, _name, _delegate(_name))
