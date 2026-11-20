"""LAN dashboard startup, GTK dispatch and playback snapshot ownership."""
from __future__ import annotations

import pathlib
import threading

import castctl
import lan_interfaces
import portal
from gi.repository import GLib


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
        self.portal_url_label.set_text(self._portal.url)
        self.portal_pin_label.set_text(self._portal.pin)
        self.portal_status_label.set_text("Available on your local network")
        return True

    def _stop_portal(self) -> None:
        current, self._portal = getattr(self, "_portal", None), None
        self._portal_ip = None
        if current is not None:
            current.stop()
        if hasattr(self, "portal_url_label"):
            self.portal_status_label.set_text("Portal stopped")
            self.portal_url_label.set_text("—")
            self.portal_pin_label.set_text("—")

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
