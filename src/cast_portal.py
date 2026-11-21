"""Shared-room portal startup, GTK dispatch and playback snapshot ownership."""
from __future__ import annotations

import pathlib
import threading
import time

import castctl
import lan_interfaces
import portal
import portal_commands
import portal_uploads
import network_activity
from network_activity_ui import NetworkActivityMixin
from cast_widgets import save_config
from gi.repository import GLib

# An early portal cast that has not started playing within this many seconds is
# treated as failed, so the completed file is cast instead of being skipped.
PORTAL_CAST_GRACE_SECONDS = 5.0


class PortalMixin(NetworkActivityMixin):
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
            fence = getattr(self, "_portal_fence", None)
            if fence is None:
                fence = self._portal_fence = portal_commands.CommandFence(
                    generation=lambda: (self.now_playing, id(self.session)),
                    owner=self._device)
            commands = portal_commands.CommandDispatcher(self._portal_apply_command, fence=fence)
            self._portal = portal.Portal(address, self._portal_dispatch,
                                         commands=commands, fence=fence)
        except (OSError, portal.PortalError) as exc:
            self._portal = None
            self._portal_ip = None
            self.portal_status_label.set_text(f"LAN portal unavailable: {exc}")
            return True
        self._portal_ip = address
        self._portal_cast_uploads = {}
        self._portal_cast_retried = set()
        self.portal_url_label.set_text(self._portal.friendly_url)
        self.portal_pin_label.set_text(self._portal.pin)
        self.portal_status_label.set_text(
            f"Available on your local network · IP {self._portal.url}")
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
        if hasattr(self, "portal_peers_label"):
            self.portal_peers_label.set_text("Peer discovery stopped")

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
        room = getattr(getattr(getattr(self, "_portal", None), "server", None), "room", None)
        participants = room.snapshot().get("participants", []) if room is not None else []
        names = [person["name"] for person in participants if isinstance(person, dict)
                 and isinstance(person.get("name"), str)]
        roster = ", ".join(names[:4])
        if len(names) > 4:
            roster += f", +{len(names) - 4} more"
        summary = portal_uploads.format_portal_activity(activity)
        presence = f"In room: {roster}" if roster else "No guests connected"
        label.set_text(f"{presence} · {summary}")
        peers = getattr(getattr(self, "_portal", None), "peers", None)
        peer_list = peers.snapshot() if peers is not None else []
        name_counts: dict[str, int] = {}
        for peer in peer_list:
            if isinstance(peer, dict) and isinstance(peer.get("name"), str):
                folded = peer["name"].casefold()
                name_counts[folded] = name_counts.get(folded, 0) + 1
        peer_names = [
            (f"{peer['name']} · {peer['id'][:6]}" if name_counts[peer["name"].casefold()] > 1
             else peer["name"])
            + (" · video, Cast" if peer.get("compatible") else " (incompatible)")
            for peer in peer_list[:4] if isinstance(peer.get("name"), str)
            and isinstance(peer.get("id"), str)
        ]
        peer_label = getattr(self, "portal_peers_label", None)
        if peer_label is not None:
            extra = len(peer_list) - len(peer_names)
            if extra > 0:
                peer_names.append(f"+{extra} more")
            available = getattr(getattr(self, "_portal", None),
                                "peer_discovery_available", False)
            peer_label.set_text(", ".join(peer_names) if peer_names else
                                ("No other SmoothCast hosts found" if available else
                                 "Peer discovery is unavailable on this network"))
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

    def _portal_apply_music_autogain(self, value: bool) -> str:
        self.cfg["music_autogain"] = value
        save_config(self.cfg)
        return "Music autogain enabled." if value else "Music autogain disabled."

    def _portal_apply_command(self, envelope: portal_commands.MutationEnvelope):
        """Reject stale commands before GTK dispatch, then run one mutation."""
        portal_commands.precheck(self, getattr(self, "_portal_fence", None), envelope)
        try:
            return self._portal_dispatch("command", {"envelope": envelope})
        except portal.PortalRequestError as exc:
            raise portal_commands.CommandError(exc.status, exc.message) from exc

    def _portal_dispatch(self, operation: str, payload: dict) -> object:
        """Marshal web requests onto GTK's main thread; never read GTK off-thread."""
        completed = threading.Event()
        cancelled = threading.Event()
        result: list[object] = []

        def run():
            if cancelled.is_set():
                return False
            try:
                result.append(self._portal_handle(operation, payload))
            except Exception as exc:
                result.append(exc)
            finally:
                completed.set()
            return False

        source_id = GLib.idle_add(run)
        if not completed.wait(4):
            cancelled.set()
            try:
                GLib.source_remove(source_id)
            except Exception:
                pass
            raise portal.PortalRequestError(503, "SmoothCast did not respond in time")
        if result and isinstance(result[0], Exception):
            raise result[0]
        return result[0] if result else {}

    def _portal_handle(self, operation: str, payload: dict) -> object:
        if self._closing:
            raise portal.PortalRequestError(503, "SmoothCast is shutting down")
        if operation == "music_autogain":
            value = payload.get("value")
            if type(value) is not bool:
                raise portal.PortalRequestError(400, "Music autogain must be on or off")
            return self._portal_apply_music_autogain(value)
        if operation == "command":
            envelope = payload.get("envelope")
            fence = getattr(self, "_portal_fence", None)
            if not isinstance(envelope, portal_commands.MutationEnvelope) or fence is None:
                raise portal.PortalRequestError(400, "Invalid command envelope")
            return portal_commands.run_mutation(self, fence, envelope)
        if operation == "status":
            position = self.tracker.value()
            duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
            title = self.np_title.get_text()
            if not title and self.now_playing:
                title = pathlib.Path(self.now_playing).name
            queue = self._portal_queue_status()
            volume = castctl.volume_percent(self.device_info)
            active = bool(self.session is not None or self.external)
            can_seek = bool(active and self.session is not None and not self.busy
                            and not self.external and self.tracker.known)
            state = {
                "title": title, "receiver": self._device(), "state": self.device_state,
                "position": position, "duration": duration, "volume": volume,
                "queue": queue, "active": active, "busy": bool(self.busy),
                "can_seek": can_seek,
                "music_autogain": bool(self.cfg.get("music_autogain", False)),
                "network_activity": network_activity.portal_entries(
                    getattr(self, "_network_activity_entries", []),
                    self._device_host(self._device()),
                ),
            }
            fence = getattr(self, "_portal_fence", None)
            if fence is not None:
                state["session_id"], state["revision"], _owner = fence.snapshot()
            return state
        handled = self._portal_queue_action(operation, payload)
        if handled is not None:
            return handled
        if operation == "cast_upload":
            upload_id = payload.get("upload_id")
            early = bool(payload.get("early"))
            accepted_uploads = getattr(self, "_portal_accepted_uploads", None)
            if accepted_uploads is None:
                accepted_uploads = self._portal_accepted_uploads = set()
            if upload_id in accepted_uploads:
                return "Upload received; casting started."
            path = self._portal_upload_path(payload)
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
        raise portal.PortalRequestError(400, "Unsupported action")
