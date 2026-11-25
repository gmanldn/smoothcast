"""GTK Info-tab card for the dedicated mesh heartbeat (issue #626).

A small, self-contained read-only card: the window builds it once and calls
``update`` on the existing mesh refresh. All wording comes from
``mesh_heartbeat.describe`` so the GTK card and the tests share one source.
GTK-only; it holds no mesh state of its own.
"""
from __future__ import annotations

from gi.repository import Gtk, Pango

import mesh_heartbeat

_ROWS = (("primary", "Coordinator"), ("state", "State"), ("beat", "Heartbeat"),
         ("uptime", "Uptime"), ("mesh", "Mesh"))


class HeartbeatCard:
    def __init__(self) -> None:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("card")
        card.add_css_class("mesh-heartbeat-card")
        heading = Gtk.Label(label="Mesh heartbeat", xalign=0.0)
        heading.add_css_class("heading")
        card.append(heading)
        sub = Gtk.Label(
            label="The first node up coordinates the mesh; this shows it is alive and what "
                  "the mesh is doing.",
            xalign=0.0, wrap=True)
        sub.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        card.append(sub)
        grid = Gtk.Grid(row_spacing=11, column_spacing=16)
        grid.set_valign(Gtk.Align.START)
        self._values: dict[str, Gtk.Label] = {}
        for index, (key, label) in enumerate(_ROWS):
            key_label = Gtk.Label(label=label, xalign=0.0)
            key_label.add_css_class("detail-key")
            value_label = Gtk.Label(label="—", xalign=0.0, wrap=False, selectable=True,
                                    ellipsize=Pango.EllipsizeMode.END)
            value_label.set_max_width_chars(32)
            value_label.set_width_chars(1)
            value_label.add_css_class("detail-value")
            grid.attach(key_label, 0, index, 1, 1)
            grid.attach(value_label, 1, index, 1, 1)
            self._values[key] = value_label
        card.append(grid)
        self._activity = Gtk.Label(label="Waiting for the mesh…", xalign=0.0, wrap=True)
        self._activity.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._activity.add_css_class("caption")
        self._activity.add_css_class("dim-label")
        card.append(self._activity)
        self.card = card

    def update(self, beat: dict | None) -> None:
        """Apply a heartbeat (or None when no mesh runs) without rebuilding the card."""
        fields = mesh_heartbeat.describe(beat)
        for key, label in self._values.items():
            text = fields.get(key, "—")
            if label.get_text() != text:
                label.set_text(text)
        activity = fields.get("activity", "")
        if self._activity.get_text() != activity:
            self._activity.set_text(activity)
