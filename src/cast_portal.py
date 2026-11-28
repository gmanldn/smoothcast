"""Shared-room portal startup, GTK dispatch and playback snapshot ownership."""
from __future__ import annotations

import guest_messages
import pathlib
import threading
import time
from typing import Any

import action_state
import castctl
import accent
import entry_name
import state_labels
import lan_interfaces
import portal
import portal_status
import portal_commands
import settings
import settings_catalog
import command_trace
import peer_discovery_ui
import network_activity
from cast_portal_host import PortalHostMixin
from cast_widgets import save_config
from gi.repository import GLib

class PortalMixin(PortalHostMixin):
    def _refresh_portal(self) -> bool:
        """Keep the small authenticated dashboard bound to the current LAN IP."""
        if self._closing:
            return False
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
            pin, self._portal_reuse_pin = getattr(self, "_portal_reuse_pin", None), None
            self._portal = portal.Portal(address, self._portal_dispatch, pin=pin,
                                         status_snapshot=snapshot.read,
                                         status_peek=snapshot.peek,
                                         commands=commands, fence=fence,
                                         pin_required=settings.PortalSettings.from_config(self.cfg).house_pin,
                                         preferred_port=settings.PortalSettings.from_config(self.cfg).port,
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
        entry = entry_name.EntryName(address, self._portal.port)
        entry.apply(True)
        self._entry_name = entry
        self._portal.attach_entry(entry)
        join_url = self._portal.join_url()
        if join_url != self._portal.url:
            print(f"SmoothCast room link: {join_url}", flush=True)
        self._portal_qr_url = join_url
        self._portal_ip = address
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
        current, self._portal = getattr(self, "_portal", None), None
        goodbye = None
        deadline = 0.0
        if entry is not None:
            if current is not None and getattr(self, "_closing", False):
                def close_entry():
                    try:
                        entry.close()
                    except Exception as exc:  # noqa: BLE001 - entry-name shutdown is best-effort and logged
                        print(f"SmoothCast entry-name shutdown failed: {type(exc).__name__}", flush=True)

                deadline = time.monotonic() + 0.3
                goodbye = threading.Thread(target=close_entry, name="smoothcast-entry-goodbye", daemon=True)
                goodbye.start()
            else:
                entry.close()
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
        try:
            if current is not None:
                current.stop()
        finally:
            if goodbye is not None:
                goodbye.join(max(0.0, deadline - time.monotonic()))
                if goodbye.is_alive():
                    print("SmoothCast entry-name shutdown timed out", flush=True)
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
            except Exception as exc:  # noqa: BLE001 - any handler failure is returned to the waiting caller
                result.append(exc)
            finally:
                completed.set()
                try:
                    self._publish_portal_status()
                except Exception:  # noqa: BLE001 - status publish is best-effort
                    pass
            return False

        run = command_trace.propagate(run) or run
        source_id = GLib.idle_add(run)
        if not completed.wait(4):
            cancelled.set()
            try:
                GLib.source_remove(source_id)
            except Exception:  # noqa: BLE001 - removing an already-gone source is harmless
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
        if operation == "room_rename":
            current = getattr(self, "_portal", None)
            if (current is None or session_key is None
                    or not current.server.session_key_is_host(session_key)):
                raise portal.PortalRequestError(403, "Only the host computer can rename this room")
            from portal_room import clean_room_name
            name = clean_room_name(payload.get("name"))
            self._rename_portal_room(name)
            return {"name": name}
        if operation in {"settings_read", "settings_update"}:
            owner: Any = self  # the window supplies this mixin's GTK owner fields
            current = getattr(self, "_portal", None)
            if (current is None or session_key is None
                    or not current.server.session_key_is_host(session_key)):
                raise portal.PortalRequestError(403, "Only the host computer can change these settings")
            if operation == "settings_read":
                return settings_catalog.host_setting_values(owner.cfg)
            try:
                key, value = settings_catalog.validate_host_setting(
                    payload.get("key"), payload.get("value"))
            except settings_catalog.HostSettingError as exc:
                raise portal.PortalRequestError(400, exc.message) from exc
            owner.cfg[key] = value
            if key == "color_scheme":
                # Selecting a fixed scheme ends time-of-day switching just as
                # it does in desktop Preferences.
                owner.cfg["auto_theme"] = False
                owner.app.scheme_action.set_state(GLib.Variant("s", value))
                owner._apply_color_scheme()
            elif key == "auto_theme":
                owner._apply_color_scheme()
            elif key == "accent":
                owner.app.apply_accent(value)
            elif key == "density":
                owner.app.apply_density(value)
                owner._refresh_responsive_layout()
            owner._sync_host_setting_widgets(key, value)
            save_config(owner.cfg)
            preferences = getattr(self, "_preferences_window", None)
            if preferences is not None:
                preferences.sync_from_owner()
            return settings_catalog.host_setting_values(owner.cfg)
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
            except Exception:  # noqa: BLE001 - a failed submission is not an accepted cast; undo dedupe then re-raise
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
