"""Shared-room portal startup, GTK dispatch and playback snapshot ownership."""
from __future__ import annotations

import guest_messages
import pathlib
import threading
import time

import action_state
import castctl
import accent
import entry_name
import state_labels
import lan_interfaces
import portal
import portal_status
import portal_commands
import command_trace
import peer_discovery_ui
import network_activity
from cast_portal_host import PortalHostMixin
from cast_portal_room import PortalRoomMixin
from portal_upload_recovery import PortalUploadRecoveryMixin
from network_activity_ui import NetworkActivityMixin
from cast_widgets import save_config
from gi.repository import GLib

class PortalMixin(PortalRoomMixin, PortalHostMixin, PortalUploadRecoveryMixin, NetworkActivityMixin):
    def _refresh_portal(self) -> bool:
        """Keep the small authenticated dashboard bound to the current LAN IP."""
        if self._closing:
            return False
        # The portal serves phones and other LAN clients. Its reachable
        # interface is independent of the selected Cast receiver's route:
        # on a multi-NIC/VPN host that route can point at a different network.
        address = lan_interfaces.select_private_lan_ip()
        if address == self._portal_ip and self._portal is not None:
            return True
        self._stop_portal()
        if not address:
            print("SmoothCast web GUI unavailable: no private LAN IPv4 address.",
                  flush=True)
            self.portal_status_label.set_text("LAN portal unavailable: no private IPv4 address found.")
            self._set_room_join_link(None, "Room unavailable — connect to a private LAN")
            return True
        try:
            snapshot = getattr(self, "_portal_status", None)
            if snapshot is None:
                snapshot = self._portal_status = portal_status.PublishedStatus()
            self._publish_portal_status()
            fence = getattr(self, "_portal_fence", None)
            if fence is None:
                fence = self._portal_fence = portal_commands.CommandFence(
                    generation=lambda: (self.now_playing, id(self.session)),
                    owner=self._device)
            commands = portal_commands.CommandDispatcher(self._portal_apply_command, fence=fence)
            # A service bounce keeps the printed PIN valid (guests still rejoin).
            pin, self._portal_reuse_pin = getattr(self, "_portal_reuse_pin", None), None
            self._portal = portal.Portal(address, self._portal_dispatch, pin=pin,
                                         status_snapshot=snapshot.read,
                                         status_peek=snapshot.peek,
                                         commands=commands, fence=fence,
                                         pin_required=bool(self.cfg.get("house_pin_enabled", False)),
                                         preferred_port=int(self.cfg.get("portal_port", 0)),
                                         link_sources=tuple(kind for kind in ("youtube", "magnet")
                                                            if self.cfg.get("portal_link_" + kind) is True))
        except (OSError, portal.PortalError):
            print("SmoothCast web GUI unavailable: room server could not bind.",
                  flush=True)
            self._portal = None
            self._portal_ip = None
            self.portal_status_label.set_text(
                "Could not start the shared room. Check the network connection and room settings."
            )
            self._set_room_join_link(None, "Room unavailable — check network settings")
            return True
        print(f"SmoothCast web GUI: {self._portal.url}", flush=True)
        # Claim the stable address so a printed QR survives DHCP changes; the
        # mesh reuses this entry and only releases it when another node is primary.
        entry = entry_name.EntryName(address, self._portal.port)
        entry.apply(True)
        self._entry_name = entry
        self._portal.attach_entry(entry)
        join_url = self._portal.join_url()
        if join_url != self._portal.url:
            print(f"SmoothCast room link: {join_url}", flush=True)
        self._portal_qr_url = join_url
        self._portal_ip = address
        # Reuse the same port across launches; never store a failed preferred bind.
        old_port = self.cfg.get("portal_port", 0)
        if old_port != self._portal.port:
            self.cfg["portal_port"] = self._portal.port
            save_config(self.cfg)
        self._portal_cast_uploads = {}
        self._portal_cast_retried = set()
        self.portal_url_label.set_text(join_url)
        self._set_room_join_link(join_url)
        self.portal_copy_button.set_sensitive(True)
        self.portal_pin_label.set_text(
            self._portal.pin if self._portal.server.pin_required else "Not required")
        self._ensure_library_indexer()
        if self._portal.port_fallback:
            self.portal_status_label.set_text(
                f"Previous room port {old_port} was in use. New link: {join_url}"
            )
        else:
            self.portal_status_label.set_text("Listening on your local network")
        self._show_portal_qr(join_url)
        import cast_mesh
        cast_mesh.start(self, address)
        self._sync_portal_activity_timer()
        self._publish_portal_status()
        if self.queue:
            self._save_room_checkpoint()
        return True


    def _stop_portal(self) -> None:
        import cast_mesh
        cast_mesh.stop(self)
        entry, self._entry_name = getattr(self, "_entry_name", None), None
        if entry is not None:
            # Release the stable address synchronously so no stale A record lingers.
            entry.close()
        current, self._portal = getattr(self, "_portal", None), None
        self._portal_ip = None
        self._portal_qr_url = None
        timer = getattr(self, "_portal_activity_timer", None)
        if timer is not None:
            try:
                GLib.source_remove(timer)
            except (ValueError, TypeError):
                pass
            self._portal_activity_timer = None
        self._portal_activity_period = None
        if current is not None:
            current.stop()
        if hasattr(self, "portal_url_label"):
            self.portal_status_label.set_text("Portal stopped")
            self.portal_copy_button.set_sensitive(False)
            self._show_portal_qr(None)
            self.portal_url_label.set_text("—")
            self._set_room_join_link(None, "Room stopped")
            self.portal_pin_label.set_text("—")
        if hasattr(self, "portal_activity_label"):
            self.portal_activity_label.set_text("No client activity")
        peer_discovery_ui.refresh_peer_links(
            self, [], available=False, status="Peer discovery stopped")


    def _portal_dispatch(self, operation: str, payload: dict) -> object:
        """Serve cached reads directly and marshal all GTK-owned work to GTK."""
        if operation == "status":
            if self._closing:
                raise portal.PortalRequestError(503, "SmoothCast is shutting down")
            snapshot = getattr(self, "_portal_status", None)
            state = snapshot.read() if snapshot is not None else None
            if state is None:
                raise portal.PortalRequestError(503, "Status snapshot is not ready")
            return state
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
                # A status-refresh fault must never hide the completed
                # command's receipt or cause the guest to replay it.
                completed.set()
                try:
                    self._publish_portal_status()
                except Exception:
                    pass
            return False

        # A GLib idle callback runs on a different context than the portal thread.
        run = command_trace.propagate(run) or run
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
        session_key = payload.get("_portal_auth_key")
        if session_key is not None:
            current = getattr(self, "_portal", None)
            if current is None or not current.server.session_key_active(session_key):
                raise portal.PortalRequestError(401, guest_messages.ACCESS_REMOVED)
        if operation == "upload_target":
            return self._portal_upload_target()
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
            position, duration = self._portal_timing()
            title = self.np_title.get_text()
            if not title and self.now_playing:
                title = pathlib.Path(self.now_playing).name
            queue = self._portal_queue_status()
            volume = castctl.volume_percent(self.device_info)
            active = bool(self.session is not None or self.external)
            can_seek = bool(active and self.session is not None and not self.busy
                            and not self.external and self.tracker.known)
            feedback = getattr(self, "_cast_feedback", None)
            media = getattr(self, "media", None) if active and not self.external else None
            kind = ("video" if getattr(media, "has_video", False) else
                    "audio" if getattr(media, "is_audio_only", False) else "")
            state = {
                "cast_feedback": feedback if feedback and feedback.get("receiver") == self._device() else None,
                "title": title, "receiver": self._device(), "state": self.device_state,
                "state_label": state_labels.present(self.device_state).label,
                "state_short": state_labels.present(self.device_state).short,
                "state_description": state_labels.present(self.device_state).accessible,
                "state_icon": state_labels.present(self.device_state).icon,
                "position": position, "duration": duration, "media_kind": kind,
                # Source seconds per wall second. The tracker is authoritative,
                # not HLS segment timestamps or a browser-side playback guess.
                "rate": (self.tracker.rate
                         if 0.05 <= self.tracker.rate <= 4.0 else 1.0),
                "volume": volume,
                "queue": queue, "queue_total": len(self.queue),
                "queue_revision": self._portal_observe_queue(),
                "library_copies": self._portal_copy_status(),
                "active": active, "busy": bool(self.busy),
                "preparing": bool(self.busy and getattr(self, "_dlna_cancel", None) is not None),
                "can_stop": action_state.can_stop(
                    self.device_state, self.session, self.external, None,
                    self.busy, getattr(self, "_dlna_cancel", None)),
                "can_play_pause": active and action_state.can_play_pause(
                    self.device_state, self.session, self.external, None, self.busy),
                "can_seek": can_seek,
                "music_autogain": bool(self.cfg.get("music_autogain", False)),
                "accent": accent.normalize(self.cfg.get("accent")),
                "network_activity": network_activity.portal_entries(
                    getattr(self, "_network_activity_entries", []),
                    self._device_host(self._device()),
                    getattr(self, "_network_activity_updated", None),
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
            target = payload.get("cast_target")
            if target is not None and self._portal_upload_target()["target_id"] != target:
                raise portal.PortalRequestError(409, "Casting target changed. The upload has not been sent to another receiver.")
            path = self._portal_upload_path(payload)
            if self.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            # A rejected request or duplicate contribution must not rename media.
            if str(path) not in self.queue and str(path) != self.now_playing:
                self._portal_note_display_name(path, payload.get("name"))
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
            try:
                self.set_selection(str(path))
                # A partial file must not be direct-cast (catt would stream a
                # truncated file); force the growing-file HLS transcode instead.
                self._portal_early = early
                reason = self._cast_path(path, 0)
                if reason is not None:
                    raise portal.PortalRequestError(409, reason)
            except Exception:
                # A failed synchronous submission is not an accepted cast.
                # Otherwise the same upload ID is silently ignored on retry.
                if upload_id:
                    accepted_uploads.discard(upload_id)
                    getattr(self, "_portal_cast_uploads", {}).pop(upload_id, None)
                raise
            finally:
                self._portal_early = False
            return "Upload received; casting started."
        raise portal.PortalRequestError(400, "Unsupported action")
