"""Room portal QR/link presentation, house-service bounce and status bridge.

Extracted from ``cast_portal.py`` unchanged so that module stays within its
INV-011 read budget; the methods run on the same ``PortalMixin`` instance.
"""
from __future__ import annotations

import hashlib

import portal
import portal_commands
import portal_join
from cast_widgets import save_config
from gi.repository import Gdk, GLib, Gtk


class PortalRoomMixin:
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
        if current is None:
            return
        joiner = getattr(current, "join_url", None)
        self.get_clipboard().set(joiner() if callable(joiner) else current.url)
        self.toast("Room link copied")
    def _refresh_portal_qr(self) -> None:
        """Repaint the room QR/link when the stable entry name changes (e.g. mesh primary)."""
        current = self._portal
        if current is None:
            return
        url = current.join_url()
        if url == getattr(self, "_portal_qr_url", None):
            return
        self._portal_qr_url = url
        self.portal_url_label.set_text(url)
        self._set_room_join_link(url)
        self._show_portal_qr(url)
    def reload_house_services(self) -> None:
        """Restart the room, mesh, library indexer and heartbeat in place.

        A relaunch of ``sc.py`` while SmoothCast runs reaches here so a changed
        checkout or settings take effect without a full restart. Playback
        ownership is untouched: the active cast, session and tracker keep
        running while the room and its helpers come back on the current LAN.
        """
        if self._closing:
            return
        current = getattr(self, "_portal", None)
        # Keep the printed PIN valid across the bounce; guests still rejoin the
        # restarted room and re-authenticate with the same code.
        self._portal_reuse_pin = current.pin if current is not None else None
        self._stop_portal()          # room, mesh and heartbeat
        # Keep the process-wide content key cache: only application exit closes it.
        self._stop_house_services(keep_fingerprint=True)  # library indexer, mesh-library
        self._refresh_portal()       # rebuild everything on the current LAN
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
    def _portal_upload_target(self) -> dict:
        """Read GTK-owned selection/status only; never perform network I/O here."""
        receiver = self._device()
        host = self._device_host(receiver)
        if not receiver or not host or not self.device_info or self.device_state == "OFFLINE":
            raise portal.PortalRequestError(409, "No reachable room receiver. Ask the host to select a TV or speaker.")
        # Target confirmation is read-only and remains available during
        # preparation of another stream. Actual cast commands still check busy.
        identity = "\\0".join((receiver, host, str(self.cfg.get("device_uuid") or "")))
        return {"receiver": receiver, "target_id": hashlib.sha256(identity.encode()).hexdigest(),
                "active": bool(self.session is not None or self.external or self.busy)}
