"""Local and LAN dashboard presentation for read-only receiver activity."""
from __future__ import annotations

import time

import castctl
import network_activity
from cast_widgets import Async
from gi.repository import Gtk


class NetworkActivityController:
    """Composition replacement for NetworkActivityMixin (#691); state and widgets stay on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _build_network_activity_card(self) -> Gtk.Box:
        w = self.w
        card, body = w._card(
            "On your network", "Read-only status from reachable Cast and DLNA receivers; updates every 15 seconds."
        )
        card.add_css_class("activity-card")
        w.network_activity_summary = Gtk.Label(
            label="Looking for active playback…", xalign=0.0, wrap=True,
        )
        w.network_activity_summary.add_css_class("section-caption")
        body.append(w.network_activity_summary)
        w.network_activity_rows = Gtk.ListBox()
        w.network_activity_rows.set_selection_mode(Gtk.SelectionMode.NONE)
        w.network_activity_rows.add_css_class("boxed-list")
        body.append(w.network_activity_rows)
        self._render_network_activity()
        return card

    def _refresh_network_activity(self) -> bool:
        """Poll discovered receivers off-thread and publish a read-only snapshot."""
        w = self.w
        if w._closing or getattr(w, "_network_activity_busy", False):
            return not w._closing
        if getattr(w, "busy", False):
            # A cast is starting: extra catt status processes would compete with
            # its receiver confirmation for CPU and the TV connection. Skip a tick.
            return True
        casts = tuple(getattr(w, "devices", ()))
        renderers = tuple(getattr(w, "dlna_devices", ()))
        if not casts and not renderers:
            w._network_activity_entries = []
            w._network_activity_updated = time.monotonic()
            self._render_network_activity()
            w._publish_portal_status()
            return True
        w._network_activity_busy = True

        def completed(entries):
            w._network_activity_busy = False
            if w._closing:
                return
            w._network_activity_entries = entries
            w._network_activity_updated = time.monotonic()
            self._render_network_activity()
            w._publish_portal_status()

        def failed(_message):
            w._network_activity_busy = False
            if not w._closing:
                w._network_activity_entries = []
                w._network_activity_updated = time.monotonic()
                self._render_network_activity()
                w._publish_portal_status()

        Async.run(
            lambda: network_activity.snapshot(list(casts), list(renderers)),
            done=completed, failed=failed, domain="background",
        )
        return True

    def _render_network_activity(self) -> None:
        w = self.w
        rows = getattr(w, "network_activity_rows", None)
        summary = getattr(w, "network_activity_summary", None)
        if rows is None or summary is None:
            return
        while child := rows.get_first_child():
            rows.remove(child)
        entries = getattr(w, "_network_activity_entries", [])
        if not entries:
            summary.set_text("No active streams reported by reachable receivers")
            empty = Gtk.Label(
                label="When someone starts a Cast or DLNA stream, it appears here. Unreachable receivers are omitted.",
                xalign=0.0, wrap=True,
            )
            empty.add_css_class("dim-label")
            rows.append(empty)
            return
        count = len(entries)
        summary.set_text(f"{count} active stream{'s' if count != 1 else ''} · refreshed every 15 seconds")
        local_host = w._device_host(w._device())
        for item in entries:
            is_local = bool(local_host and item.get("host") == local_host)
            tag = " · This SmoothCast" if is_local else ""
            position = network_activity._number(item.get("position"))
            duration = network_activity._number(item.get("duration"))
            timing = ""
            if position is not None:
                timing = f" · {castctl.fmt_time(position)}"
                if duration is not None:
                    timing += f" / {castctl.fmt_time(duration)}"
            title = Gtk.Label(label=item["title"], xalign=0.0, wrap=True)
            title.set_selectable(True)
            title.add_css_class("heading")
            detail = Gtk.Label(
                label=f"{item['receiver']} · {item['protocol']} · {item['state']}{timing}{tag}",
                xalign=0.0, wrap=True,
            )
            detail.add_css_class("caption")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            box.append(title)
            box.append(detail)
            box.set_margin_top(5)
            box.set_margin_bottom(5)
            rows.append(box)
