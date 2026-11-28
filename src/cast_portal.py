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
from cast_widgets import save_config
from gi.repository import GLib

class PortalController:
    """Composition replacement for PortalMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _refresh_portal(self) -> bool:
        """Keep the small authenticated dashboard bound to the current LAN IP."""
        w = self.w
        if w._closing:
            return False
        address = lan_interfaces.select_private_lan_ip()
        if address == w._portal_ip and w._portal is not None:
            return True
        w._stop_portal()
        if not address:
            print("SmoothCast web GUI unavailable: no private LAN IPv4 address.",
                  flush=True)
            w.portal_status_label.set_text("LAN portal unavailable: no private IPv4 address found.")
            w._set_room_join_link(None, "Room unavailable — connect to a private LAN")
            return True
        try:
            snapshot = getattr(w, "_portal_status", None)
            if snapshot is None:
                snapshot = w._portal_status = portal_status.PublishedStatus()
            w._publish_portal_status()
            fence = getattr(w, "_portal_fence", None)
            if fence is None:
                fence = w._portal_fence = portal_commands.CommandFence(
                    generation=lambda: (w.now_playing, id(w.session)),
                    owner=w._device)
            commands = portal_commands.CommandDispatcher(w._portal_apply_command, fence=fence)
            pin, w._portal_reuse_pin = getattr(w, "_portal_reuse_pin", None), None
            w._portal = portal.Portal(address, w._portal_dispatch, pin=pin,
                                         status_snapshot=snapshot.read,
                                         status_peek=snapshot.peek,
                                         commands=commands, fence=fence,
                                         pin_required=settings.PortalSettings.from_config(w.cfg).house_pin,
                                         preferred_port=settings.PortalSettings.from_config(w.cfg).port,
                                         link_sources=tuple(kind for kind in ("youtube", "magnet")
                                                            if w.cfg.get("portal_link_" + kind) is True))
        except (OSError, portal.PortalError):
            print("SmoothCast web GUI unavailable: room server could not bind.",
                  flush=True)
            w._portal = None
            w._portal_ip = None
            w.portal_status_label.set_text(
                "Could not start the shared room. Check the network connection and room settings."
            )
            w._set_room_join_link(None, "Room unavailable — check network settings")
            return True
        print(f"SmoothCast web GUI: {w._portal.url}", flush=True)
        entry = entry_name.EntryName(address, w._portal.port)
        entry.apply(True)
        w._entry_name = entry
        w._portal.attach_entry(entry)
        join_url = w._portal.join_url()
        if join_url != w._portal.url:
            print(f"SmoothCast room link: {join_url}", flush=True)
        w._portal_qr_url = join_url
        w._portal_ip = address
        old_port = w.cfg.get("portal_port", 0)
        if old_port != w._portal.port:
            w.cfg["portal_port"] = w._portal.port
            save_config(w.cfg)
        w._portal_cast_uploads = {}
        w._portal_cast_retried = set()
        w.portal_url_label.set_text(join_url)
        w._set_room_join_link(join_url)
        w.portal_copy_button.set_sensitive(True)
        w.portal_pin_label.set_text(
            w._portal.pin if w._portal.server.pin_required else "Not required")
        w._ensure_library_indexer()
        if w._portal.port_fallback:
            w.portal_status_label.set_text(
                f"Previous room port {old_port} was in use. New link: {join_url}"
            )
        else:
            w.portal_status_label.set_text("Listening on your local network")
        w._show_portal_qr(join_url)
        import cast_mesh
        cast_mesh.start(w, address)
        w._sync_portal_activity_timer()
        w._publish_portal_status()
        if w.queue:
            w._save_room_checkpoint()
        return True


    def _stop_portal(self) -> None:
        w = self.w
        import cast_mesh
        cast_mesh.stop(w)
        entry, w._entry_name = getattr(w, "_entry_name", None), None
        current, w._portal = getattr(w, "_portal", None), None
        goodbye = None
        deadline = 0.0
        if entry is not None:
            if current is not None and getattr(w, "_closing", False):
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
        w._portal_ip = None
        w._portal_qr_url = None
        timer = getattr(w, "_portal_activity_timer", None)
        if timer is not None:
            try:
                GLib.source_remove(timer)
            except (ValueError, TypeError):
                pass
            w._portal_activity_timer = None
        w._portal_activity_period = None
        try:
            if current is not None:
                current.stop()
        finally:
            if goodbye is not None:
                goodbye.join(max(0.0, deadline - time.monotonic()))
                if goodbye.is_alive():
                    print("SmoothCast entry-name shutdown timed out", flush=True)
        if hasattr(w, "portal_url_label"):
            w.portal_status_label.set_text("Portal stopped")
            w.portal_copy_button.set_sensitive(False)
            w._show_portal_qr(None)
            w.portal_url_label.set_text("—")
            w._set_room_join_link(None, "Room stopped")
            w.portal_pin_label.set_text("—")
        if hasattr(w, "portal_activity_label"):
            w.portal_activity_label.set_text("No client activity")
        peer_discovery_ui.refresh_peer_links(
            w, [], available=False, status="Peer discovery stopped")


    def _portal_dispatch(self, operation: str, payload: dict) -> object:
        """Serve cached reads directly and marshal all GTK-owned work to GTK."""
        w = self.w
        if operation == "status":
            if w._closing:
                raise portal.PortalRequestError(503, "SmoothCast is shutting down")
            snapshot = getattr(w, "_portal_status", None)
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
                result.append(w._portal_handle(operation, payload))
            except Exception as exc:  # noqa: BLE001 - any handler failure is returned to the waiting caller
                result.append(exc)
            finally:
                completed.set()
                try:
                    w._publish_portal_status()
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
        w = self.w
        if w._closing:
            raise portal.PortalRequestError(503, "SmoothCast is shutting down")
        session_key = payload.get("_portal_auth_key")
        if session_key is not None:
            current = getattr(w, "_portal", None)
            if current is None or not current.server.session_key_active(session_key):
                raise portal.PortalRequestError(401, guest_messages.ACCESS_REMOVED)
        if operation == "room_rename":
            current = getattr(w, "_portal", None)
            if (current is None or session_key is None
                    or not current.server.session_key_is_host(session_key)):
                raise portal.PortalRequestError(403, "Only the host computer can rename this room")
            from portal_room import clean_room_name
            name = clean_room_name(payload.get("name"))
            w._rename_portal_room(name)
            return {"name": name}
        if operation in {"settings_read", "settings_update"}:
            owner: Any = w  # the window supplies this mixin's GTK owner fields
            current = getattr(w, "_portal", None)
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
            preferences = getattr(w, "_preferences_window", None)
            if preferences is not None:
                preferences.sync_from_owner()
            return settings_catalog.host_setting_values(owner.cfg)
        if operation == "upload_target":
            return w._portal_upload_target()
        if operation == "music_autogain":
            value = payload.get("value")
            if type(value) is not bool:
                raise portal.PortalRequestError(400, "Music autogain must be on or off")
            return w._portal_apply_music_autogain(value)
        if operation == "command":
            envelope = payload.get("envelope")
            fence = getattr(w, "_portal_fence", None)
            if not isinstance(envelope, portal_commands.MutationEnvelope) or fence is None:
                raise portal.PortalRequestError(400, "Invalid command envelope")
            return portal_commands.run_mutation(w, fence, envelope)
        if operation == "status":
            position, duration = w._portal_timing()
            title = w.np_title.get_text()
            if not title and w.now_playing:
                title = pathlib.Path(w.now_playing).name
            queue = w._portal_queue_status()
            volume = castctl.volume_percent(w.device_info)
            active = bool(w.session is not None or w.external)
            can_seek = bool(active and w.session is not None and not w.busy
                            and not w.external and w.tracker.known)
            feedback = getattr(w, "_cast_feedback", None)
            media = getattr(w, "media", None) if active and not w.external else None
            kind = ("video" if getattr(media, "has_video", False) else
                    "audio" if getattr(media, "is_audio_only", False) else "")
            state = {
                "cast_feedback": feedback if feedback and feedback.get("receiver") == w._device() else None,
                "title": title, "receiver": w._device(), "state": w.device_state,
                "state_label": state_labels.present(w.device_state).label,
                "state_short": state_labels.present(w.device_state).short,
                "state_description": state_labels.present(w.device_state).accessible,
                "state_icon": state_labels.present(w.device_state).icon,
                "position": position, "duration": duration, "media_kind": kind,
                # Source seconds per wall second. The tracker is authoritative,
                # not HLS segment timestamps or a browser-side playback guess.
                "rate": (w.tracker.rate
                         if 0.05 <= w.tracker.rate <= 4.0 else 1.0),
                "volume": volume,
                "queue": queue, "queue_total": len(w.queue),
                "queue_revision": w._portal_observe_queue(),
                "library_copies": w._portal_copy_status(),
                "active": active, "busy": bool(w.busy),
                "preparing": bool(w.busy and getattr(w, "_dlna_cancel", None) is not None),
                "can_stop": action_state.can_stop(
                    w.device_state, w.session, w.external, None,
                    w.busy, getattr(w, "_dlna_cancel", None)),
                "can_play_pause": active and action_state.can_play_pause(
                    w.device_state, w.session, w.external, None, w.busy),
                "can_seek": can_seek,
                "music_autogain": bool(w.cfg.get("music_autogain", False)),
                "accent": accent.normalize(w.cfg.get("accent")),
                "network_activity": network_activity.portal_entries(
                    getattr(w, "_network_activity_entries", []),
                    w._device_host(w._device()),
                    getattr(w, "_network_activity_updated", None),
                ),
            }
            fence = getattr(w, "_portal_fence", None)
            if fence is not None:
                state["session_id"], state["revision"], _owner = fence.snapshot()
            return state
        handled = w._portal_queue_action(operation, payload)
        if handled is not None:
            return handled
        if operation == "cast_upload":
            upload_id = payload.get("upload_id")
            early = bool(payload.get("early"))
            accepted_uploads = getattr(w, "_portal_accepted_uploads", None)
            if accepted_uploads is None:
                accepted_uploads = w._portal_accepted_uploads = set()
            if upload_id in accepted_uploads:
                return "Upload received; casting started."
            target = payload.get("cast_target")
            if target is not None and w._portal_upload_target()["target_id"] != target:
                raise portal.PortalRequestError(409, "Casting target changed. The upload has not been sent to another receiver.")
            path = w._portal_upload_path(payload)
            if w.busy:
                raise portal.PortalRequestError(409, "SmoothCast is finishing another command")
            # A rejected request or duplicate contribution must not rename media.
            if str(path) not in w.queue and str(path) != w.now_playing:
                w._portal_note_display_name(path, payload.get("name"))
            if upload_id:
                accepted_uploads.add(upload_id)
                if early:
                    # Tracked only until it is confirmed playing or declared
                    # stale; a failed early cast is discarded so the finished
                    # file is cast instead.
                    casting = getattr(w, "_portal_cast_uploads", None)
                    if casting is None:
                        casting = w._portal_cast_uploads = {}
                    casting[upload_id] = (str(path), time.monotonic())
            try:
                w.set_selection(str(path))
                # A partial file must not be direct-cast (catt would stream a
                # truncated file); force the growing-file HLS transcode instead.
                w._portal_early = early
                reason = w._cast_path(path, 0)
                if reason is not None:
                    raise portal.PortalRequestError(409, reason)
            except Exception:  # noqa: BLE001 - a failed submission is not an accepted cast; undo dedupe then re-raise
                # A failed synchronous submission is not an accepted cast.
                # Otherwise the same upload ID is silently ignored on retry.
                if upload_id:
                    accepted_uploads.discard(upload_id)
                    getattr(w, "_portal_cast_uploads", {}).pop(upload_id, None)
                raise
            finally:
                w._portal_early = False
            return "Upload received; casting started."
        raise portal.PortalRequestError(400, "Unsupported action")
