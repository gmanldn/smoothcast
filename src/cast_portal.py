"""Shared-room portal startup, GTK dispatch and playback snapshot ownership."""
from __future__ import annotations

import pathlib
import threading
import time

import castctl
import state_labels
import lan_interfaces
import portal
import portal_status
import portal_commands
import portal_join
import peer_discovery_ui
import portal_uploads
import network_activity
from cast_portal_host import PortalHostMixin
from portal_upload_recovery import PortalUploadRecoveryMixin
from network_activity_ui import NetworkActivityMixin
from cast_widgets import Async, save_config
from gi.repository import Gdk, GLib, Gtk

class PortalMixin(PortalHostMixin, PortalUploadRecoveryMixin, NetworkActivityMixin):
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
            self.portal_status_label.set_text("LAN portal unavailable: no private IPv4 address found.")
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
            self._portal = portal.Portal(address, self._portal_dispatch,
                                         status_snapshot=snapshot.read,
                                         commands=commands, fence=fence,
                                         pin_required=bool(self.cfg.get("house_pin_enabled", False)),
                                         preferred_port=int(self.cfg.get("portal_port", 0)))
        except (OSError, portal.PortalError) as exc:
            self._portal = None
            self._portal_ip = None
            self.portal_status_label.set_text(f"LAN portal unavailable: {exc}")
            return True
        self._portal_ip = address
        # Reuse the same port across launches; never store a failed preferred bind.
        old_port = self.cfg.get("portal_port", 0)
        if old_port != self._portal.port:
            self.cfg["portal_port"] = self._portal.port
            save_config(self.cfg)
        self._portal_cast_uploads = {}
        self._portal_cast_retried = set()
        self.portal_url_label.set_text(self._portal.url)
        self.portal_copy_button.set_sensitive(True)
        self.portal_pin_label.set_text(
            self._portal.pin if self._portal.server.pin_required else "Not required")
        self._ensure_library_indexer()
        if self._portal.port_fallback:
            self.portal_status_label.set_text(
                f"Previous room port {old_port} was in use. New link: {self._portal.url}"
            )
        else:
            self.portal_status_label.set_text("Listening on your local network")
        self._show_portal_qr(self._portal.url)
        import cast_mesh
        cast_mesh.start(self, address)
        self._sync_portal_activity_timer()
        self._publish_portal_status()
        return True

    def _show_portal_qr(self, url: str | None) -> None:
        picture = self.portal_qr_picture
        texture = None
        if url is not None:
            try:
                png = portal_join.qr_png(url)
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
            except (ImportError, ValueError, GLib.Error):
                self.portal_status_label.set_text("QR unavailable. Use Copy link to join.")
        picture.set_paintable(texture)
        self.portal_qr_button.set_sensitive(texture is not None)

    def _copy_portal_link(self, _button: Gtk.Button) -> None:
        current = self._portal
        if current is not None:
            self.get_clipboard().set(current.url)
            self.toast("Room link copied")

    def _stop_portal(self) -> None:
        import cast_mesh
        cast_mesh.stop(self)
        current, self._portal = getattr(self, "_portal", None), None
        self._portal_ip = None
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
            self.portal_pin_label.set_text("—")
        if hasattr(self, "portal_activity_label"):
            self.portal_activity_label.set_text("No client activity")
        peer_discovery_ui.refresh_peer_links(
            self, [], available=False, status="Peer discovery stopped")

    def _sync_portal_activity_timer(self) -> None:
        """Room UI refreshes once per second only when the window is mapped."""
        if (self._closing or self._portal is None
                or not getattr(self, "_timers_enabled", False)):
            return
        period = 1000 if self.get_mapped() else 15000
        current = getattr(self, "_portal_activity_timer", None)
        if current is not None and period == getattr(self, "_portal_activity_period", None):
            return
        if current is not None:
            GLib.source_remove(current)
        self._portal_activity_period = period
        self._portal_activity_timer = GLib.timeout_add(period, self._refresh_portal_activity)

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
        ids = tuple(person["id"] for person in participants
                    if isinstance(person, dict) and isinstance(person.get("id"), str))
        if hasattr(self, "portal_guest_dropdown") and ids != getattr(self, "portal_guest_ids", ()):
            prior = getattr(self, "portal_guest_ids", ())
            selected = self.portal_guest_dropdown.get_selected()
            chosen = prior[selected] if selected < len(prior) else None
            labels = [str(person.get("name", "Guest")) for person in participants
                      if isinstance(person, dict) and isinstance(person.get("id"), str)]
            self.portal_guest_ids = ids
            self.portal_guest_dropdown.set_model(
                Gtk.StringList.new(labels if labels else ["No guests connected"]))
            self.portal_guest_dropdown.set_selected(
                ids.index(chosen) if chosen in ids else 0)
            self.portal_guest_dropdown.set_sensitive(bool(ids))
            self.portal_revoke_button.set_sensitive(bool(ids))
        summary = portal_uploads.format_portal_activity(activity)
        presence = f"In room: {roster}" if roster else "No guests connected"
        screens = getattr(getattr(self._portal, "server", None), "screens", None)
        try:
            screen_rows = screens.snapshot() if screens is not None else []
        except Exception:
            screen_rows = []
        ready = [f"{row['name']} ({row['state']})" for row in screen_rows[:3]
                 if isinstance(row, dict) and row.get("ready")]
        shown = f" · Screens: {', '.join(ready)}" if ready else ""
        label.set_text(f"{presence} · {summary}{shown}")
        peers = getattr(getattr(self, "_portal", None), "peers", None)
        peer_list = peers.snapshot() if peers is not None else []
        available = getattr(getattr(self, "_portal", None),
                            "peer_discovery_available", False)
        peer_discovery_ui.refresh_peer_links(self, peer_list, available=available)
        mesh = getattr(self, "_mesh_library", None)
        if mesh is not None:
            Async.run(lambda: mesh.observe_peers(peer_list), domain="background")
        self._reconcile_portal_casts()
        import cast_mesh
        cast_mesh.push_clients(self)
        return True

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
                self._publish_portal_status()
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

    def _publish_portal_status(self) -> None:
        """Publish GTK-owned status for HTTP threads without dispatch waits."""
        snapshot = getattr(self, "_portal_status", None)
        if snapshot is None or self._closing:
            return
        try:
            state = self._portal_handle("status", {})
        except Exception as exc:
            console = getattr(self, "_console", None)
            if console is not None:
                console(f"Could not publish room status: {exc}")
            return
        if isinstance(state, dict):
            snapshot.publish(state)

    def _portal_handle(self, operation: str, payload: dict) -> object:
        if self._closing:
            raise portal.PortalRequestError(503, "SmoothCast is shutting down")
        session_key = payload.get("_portal_auth_key")
        if session_key is not None:
            current = getattr(self, "_portal", None)
            if current is None or not current.server.session_key_active(session_key):
                raise portal.PortalRequestError(401, "Room access was revoked")
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
                "state_label": state_labels.present(self.device_state).label,
                "state_short": state_labels.present(self.device_state).short,
                "state_description": state_labels.present(self.device_state).accessible,
                "state_icon": state_labels.present(self.device_state).icon,
                "position": position, "duration": duration, "volume": volume,
                "queue": queue, "queue_revision": self._portal_observe_queue(),
                "active": active, "busy": bool(self.busy),
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
