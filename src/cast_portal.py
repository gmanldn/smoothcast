"""LAN dashboard startup, GTK dispatch and playback snapshot ownership."""
from __future__ import annotations

import pathlib
import threading
import os
import stat
import time

import castctl
import lan_interfaces
import portal
import portal_uploads
from gi.repository import GLib

# An early portal cast that has not started playing within this many seconds is
# treated as failed, so the completed file is cast instead of being skipped.
PORTAL_CAST_GRACE_SECONDS = 5.0


class PortalMixin:
    def _refresh_portal(self) -> bool:
        """Keep the small authenticated dashboard bound to the current LAN IP."""
        if self._closing:
            return False
        receiver = self._device_host(self._device())
        address = lan_interfaces.select_private_lan_ip(receiver)
        if address == self._portal_ip and self._portal is not None:
            return True
        self._stop_portal()
        if not address:
            self.portal_status_label.set_text("LAN portal unavailable: no private IPv4 address found.")
            return True
        try:
            self._portal = portal.Portal(address, self._portal_dispatch)
        except (OSError, portal.PortalError) as exc:
            self._portal = None
            self._portal_ip = None
            self.portal_status_label.set_text(f"LAN portal unavailable: {exc}")
            return True
        self._portal_ip = address
        self._portal_cast_uploads = {}
        self._portal_cast_retried = set()
        self.portal_url_label.set_text(self._portal.url)
        self.portal_pin_label.set_text(self._portal.pin)
        self.portal_status_label.set_text("Available on your local network")
        if getattr(self, "_portal_activity_timer", None) is None:
            self._portal_activity_timer = GLib.timeout_add_seconds(1, self._refresh_portal_activity)
        return True

    def _stop_portal(self) -> None:
        current, self._portal = getattr(self, "_portal", None), None
        self._portal_ip = None
        timer = getattr(self, "_portal_activity_timer", None)
        if timer is not None:
            try:
                GLib.source_remove(timer)
            except (ValueError, TypeError):
                pass
            self._portal_activity_timer = None
        if current is not None:
            current.stop()
        if hasattr(self, "portal_url_label"):
            self.portal_status_label.set_text("Portal stopped")
            self.portal_url_label.set_text("—")
            self.portal_pin_label.set_text("—")
        if hasattr(self, "portal_activity_label"):
            self.portal_activity_label.set_text("No client activity")

    def _refresh_portal_activity(self) -> bool:
        """Show what LAN clients are sending or casting, refreshed every second."""
        label = getattr(self, "portal_activity_label", None)
        if label is None or getattr(self, "_closing", False):
            self._portal_activity_timer = None
            return False
        uploads = getattr(getattr(self, "_portal", None), "uploads", None)
        try:
            activity = uploads.snapshot() if uploads is not None else []
        except Exception:
            activity = []
        label.set_text(portal_uploads.format_portal_activity(activity))
        self._reconcile_portal_casts()
        return True

    def _reconcile_portal_casts(self) -> None:
        """Drop early casts that never started so the finished file still casts."""
        casting = getattr(self, "_portal_cast_uploads", None)
        if not casting:
            return
        for upload_id, (path, _started) in list(casting.items()):
            if self.now_playing == path:
                casting.pop(upload_id, None)  # confirmed playing; no longer tracked
        now = time.monotonic()
        stale = portal_uploads.stale_early_casts(
            casting, now=now, busy=bool(self.busy),
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
            if status and status.get("complete"):
                retried = getattr(self, "_portal_cast_retried", None)
                if retried is not None and upload_id not in retried:
                    retried.add(upload_id)
                    GLib.idle_add(self._retry_portal_cast, upload_id, path)

    def _retry_portal_cast(self, upload_id: str, path: str) -> bool:
        if self.busy or getattr(self, "_closing", False):
            return False
        casting = getattr(self, "_portal_cast_uploads", None)
        if casting is None:
            return False
        casting[upload_id] = (path, time.monotonic())
        accepted = getattr(self, "_portal_accepted_uploads", None)
        if accepted is not None:
            accepted.add(upload_id)
        self._cast_path(pathlib.Path(path), 0)
        return False

    def _portal_dispatch(self, operation: str, payload: dict) -> dict | str:
        """Marshal web requests onto GTK's main thread; never read GTK off-thread."""
        completed = threading.Event()
        result: list[object] = []

        def run() -> bool:
            try:
                result.append(self._portal_handle(operation, payload))
            except Exception as exc:
                result.append(exc)
            finally:
                completed.set()
            return False

        GLib.idle_add(run)
        if not completed.wait(4):
            raise portal.PortalRequestError(503, "SmoothCast did not respond in time")
        if result and isinstance(result[0], Exception):
            raise result[0]
        return result[0] if result else {}

    def _portal_handle(self, operation: str, payload: dict) -> dict | str:
        if self._closing:
            raise portal.PortalRequestError(503, "SmoothCast is shutting down")
        if operation == "status":
            position = self.tracker.value()
            duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
            title = self.np_title.get_text()
            if not title and self.now_playing:
                title = pathlib.Path(self.now_playing).name
            queue = [pathlib.Path(path).name for path in self.queue[:100]]
            volume = castctl.volume_percent(self.device_info)
            active = bool(self.session is not None or self.external)
            can_seek = bool(active and self.session is not None and not self.busy
                            and not self.external and self.tracker.known)
            return {
                "title": title, "receiver": self._device(), "state": self.device_state,
                "position": position, "duration": duration, "volume": volume,
                "queue": queue, "active": active, "busy": bool(self.busy),
                "can_seek": can_seek,
            }
        if operation == "cast_upload":
            upload_id = payload.get("upload_id")
            early = bool(payload.get("early"))
            accepted_uploads = getattr(self, "_portal_accepted_uploads", None)
            if accepted_uploads is None:
                accepted_uploads = self._portal_accepted_uploads = set()
            if upload_id in accepted_uploads:
                return "Upload received; casting started."
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
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            if upload_id:
                accepted_uploads.add(upload_id)
                if early:
                    # Tracked only until it is confirmed playing or declared
                    # stale; a failed early cast is discarded so the finished
                    # file is cast instead.
                    casting = getattr(self, "_portal_cast_uploads", None)
                    if casting is None:
                        casting = self._portal_cast_uploads = {}
                    casting[upload_id] = (str(path), time.monotonic())
            self.set_selection(str(path))
            # A partial file must not be direct-cast (catt would stream a
            # truncated file); force the growing-file HLS transcode instead.
            self._portal_early = early
            try:
                self._cast_path(path, 0)
            finally:
                self._portal_early = False
            return "Upload received; casting started."
        if self.busy:
            raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
        if operation == "play_pause":
            if not self.play_button.get_sensitive():
                raise portal.PortalRequestError(409, "Playback is not available right now")
            self.toggle_play()
            return "Playback command sent; the dashboard will refresh with receiver state."
        if operation == "stop":
            if not self.stop_button.get_sensitive():
                raise portal.PortalRequestError(409, "Nothing SmoothCast can stop right now")
            self.stop_stream()
            return "Stop requested; the dashboard will refresh with receiver state."
        if operation == "seek":
            if (self.session is None or self.external or not self.tracker.known
                    or self.busy or not self.tracker.duration):
                raise portal.PortalRequestError(409, "Seeking is not available for this stream")
            self.seek_to(payload["value"])
            return "Seek requested; the dashboard will refresh with receiver state."
        if operation == "volume":
            if self.device_state == "OFFLINE" or not self.volume_scale.get_sensitive():
                raise portal.PortalRequestError(409, "Receiver volume is unavailable")
            self.volume_scale.set_value(payload["value"])
            return "Volume change requested; the dashboard will refresh with receiver state."
        raise portal.PortalRequestError(400, "Unsupported action")
