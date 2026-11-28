"""Room portal QR/link presentation, house-service bounce and status bridge.

Extracted from ``cast_portal.py`` unchanged so that module stays within its
INV-011 read budget; ``PortalRoomController`` drives the ``MainWindow``.
"""
from __future__ import annotations

import paths

import hashlib

import portal
import portal_commands
import portal_join
from cast_widgets import save_config
from gi.repository import Gdk, GLib, Gtk


class PortalRoomController:
    """Composition replacement for PortalRoomMixin (#691); state and widgets stay on the window."""

    def __init__(self, window, glib=None, save=None) -> None:
        self.w = window
        self.save = save or save_config
        self.glib = glib or GLib

    def _show_portal_qr(self, url: str | None) -> None:
        w = self.w
        picture = w.portal_qr_picture
        texture = None
        if url is not None:
            try:
                png = portal_join.qr_png(url)
                texture = Gdk.Texture.new_from_bytes(self.glib.Bytes.new(png))
            except (ImportError, ValueError, self.glib.Error):
                w.portal_status_label.set_text("QR unavailable. Use Copy link to join.")
        picture.set_paintable(texture)
        w.portal_qr_button.set_sensitive(texture is not None)
    def _copy_portal_link(self, _button: Gtk.Button) -> None:
        w = self.w
        current = w._portal
        if current is None:
            return
        joiner = getattr(current, "join_url", None)
        w.get_clipboard().set(joiner() if callable(joiner) else current.url)
        w.toast("Room link copied")
    def _refresh_portal_qr(self) -> None:
        """Repaint the room QR/link when the stable entry name changes (e.g. mesh primary)."""
        w = self.w
        current = w._portal
        if current is None:
            return
        url = current.join_url()
        if url == getattr(w, "_portal_qr_url", None):
            return
        w._portal_qr_url = url
        w.portal_url_label.set_text(url)
        w._set_room_join_link(url)
        self._show_portal_qr(url)
    def reload_house_services(self) -> None:
        """Restart the room, mesh, library indexer and heartbeat in place.

        A relaunch of ``sc.py`` while SmoothCast runs reaches here so a changed
        checkout or settings take effect without a full restart. Playback
        ownership is untouched: the active cast, session and tracker keep
        running while the room and its helpers come back on the current LAN.
        """
        w = self.w
        if w._closing:
            return
        current = getattr(w, "_portal", None)
        # Keep the printed PIN valid across the bounce; guests still rejoin the
        # restarted room and re-authenticate with the same code.
        w._portal_reuse_pin = current.pin if current is not None else None
        w._stop_portal()          # room, mesh and heartbeat
        # Keep the process-wide content key cache: only application exit closes it.
        w._stop_house_services(keep_fingerprint=True)  # library indexer, mesh-library
        w._refresh_portal()       # rebuild everything on the current LAN
    def _sync_portal_activity_timer(self) -> None:
        """Room UI refreshes once per second only when the window is mapped."""
        w = self.w
        if (w._closing or w._portal is None
                or not getattr(w, "_timers_enabled", False)):
            return
        period = 1000 if w.get_mapped() else 15000
        current = getattr(w, "_portal_activity_timer", None)
        if current is not None and period == getattr(w, "_portal_activity_period", None):
            return
        if current is not None:
            self.glib.source_remove(current)
        w._portal_activity_period = period
        w._portal_activity_timer = self.glib.timeout_add(period, w._refresh_portal_activity)
    def _portal_apply_music_autogain(self, value: bool) -> str:
        w = self.w
        w.cfg["music_autogain"] = value
        self.save(w.cfg)
        return "Music autogain enabled." if value else "Music autogain disabled."
    def _portal_apply_command(self, envelope: portal_commands.MutationEnvelope):
        """Reject stale commands before GTK dispatch, then run one mutation."""
        w = self.w
        portal_commands.precheck(w, getattr(w, "_portal_fence", None), envelope)
        try:
            return w._portal_dispatch("command", {"envelope": envelope})
        except portal.PortalRequestError as exc:
            raise portal_commands.CommandError(exc.status, exc.message) from exc
    def _rename_portal_room(self, value: object) -> None:
        """Rename the existing room without restarting its services."""
        w = self.w
        from portal_room import clean_room_name

        name = clean_room_name(value)
        if w.cfg.get("room_name") != name:
            w.cfg["room_name"] = name
            self.save(w.cfg)
            w._publish_portal_status()
            w.toast("Room name updated")

    def _publish_portal_status(self) -> None:
        """Publish GTK-owned status for HTTP threads without dispatch waits."""
        w = self.w
        from portal_room import clean_room_name

        label = getattr(w, "portal_room_name_label", None)
        name = clean_room_name(w.cfg.get("room_name"))
        if label is not None and label.get_text() != name:
            label.set_text(name)
        snapshot = getattr(w, "_portal_status", None)
        if snapshot is None or w._closing:
            return
        current = getattr(w, "_portal", None)
        room = getattr(getattr(current, "server", None), "room", None)
        if room is not None:
            room.set_name(w.cfg.get("room_name"))
        try:
            state = w._portal_handle("status", {})
        except Exception as exc:  # noqa: BLE001 - a failed status publish is logged to the console
            console = getattr(w, "_console", None)
            if console is not None:
                console(f"Could not publish room status: {exc}")
            return
        if isinstance(state, dict):
            import stream_health

            # Tiny bounded file written by the HLS server process (#49).
            measured = stream_health.read_snapshot(paths.cache_dir())
            if measured is not None:
                state["stream_health"] = measured
            chapters = getattr(getattr(w, "media", None), "chapters", ()) or ()
            if chapters and not w.external:
                # Same chapters the desktop menu shows, so the web room can jump to them (#39).
                state["chapters"] = [{"start": round(float(c.start), 2), "title": str(c.title)[:80]}
                                     for c in chapters[:128]]
            if w.external:
                from playback_state import external_details, external_media_labels, external_runtime
                from cast_widgets import fmt_time

                state["title"], state["media_size"] = external_media_labels(w.device_info)
                state["media_details"] = external_details(w.device_info)
                runtime = external_runtime(w.device_info)
                if runtime is not None:
                    state["length_label"] = fmt_time(runtime[1])
                elif str((w.device_info or {}).get("stream_type") or "").upper() == "LIVE":
                    state["length_label"] = "Live"
                else:
                    state["length_label"] = "Length unknown"
            snapshot.publish(state)
    def _portal_upload_target(self) -> dict:
        """Read GTK-owned selection/status only; never perform network I/O here."""
        w = self.w
        receiver = w._device()
        host = w._device_host(receiver)
        if not receiver or not host or not w.device_info or w.device_state == "OFFLINE":
            raise portal.PortalRequestError(409, "No reachable room receiver. Ask the host to select a TV or speaker.")
        # Target confirmation is read-only and remains available during
        # preparation of another stream. Actual cast commands still check busy.
        identity = "\\0".join((receiver, host, str(w.cfg.get("device_uuid") or "")))
        return {"receiver": receiver, "target_id": hashlib.sha256(identity.encode()).hexdigest(),
                "active": bool(w.session is not None or w.external or w.busy)}
