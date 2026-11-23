"""Desktop "Find in the house" window: search every shared library (#413)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk

import find_results
import portal
from cast_widgets import Async

DEBOUNCE_MS = 150


class FindWindow(Adw.Window):
    def __init__(self, owner) -> None:
        super().__init__(transient_for=owner, modal=False, title="Find in the house")
        self.owner = owner
        self._timer = 0
        self._ticket = 0
        self.set_default_size(560, 600)
        self.entry = Gtk.SearchEntry(placeholder_text="Search films, shows and music in every computer")
        self.entry.connect("search-changed", self._queue_search)
        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("dim-label")
        self.status.set_accessible_role(Gtk.AccessibleRole.STATUS)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.list)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        box.append(self.entry)
        box.append(self.status)
        box.append(scroller)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(box)
        self.set_content(view)
        self.entry.grab_focus()

    def _queue_search(self, _entry) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(DEBOUNCE_MS, self._run)

    def _run(self) -> bool:
        self._timer = 0
        text = self.entry.get_text().strip()
        self._ticket += 1
        ticket = self._ticket
        if not text:
            self._render({"groups": []}, "")
            return False
        self.status.set_text("Searching...")
        Async.run(lambda: self.owner._house_search(text),
                  done=lambda data: ticket == self._ticket and self._render(data, text),
                  failed=lambda _e: self.status.set_text("Search is unavailable right now."),
                  domain="media", valid=lambda: self.get_visible())
        return False

    def _render(self, data: dict, text: str) -> None:
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        rows = find_results.flatten(data)
        for item in rows:
            row = Adw.ActionRow(title=GLib.markup_escape_text(item.title),
                                subtitle=GLib.markup_escape_text(item.subtitle))
            if item.key:
                button = Gtk.Button(label="Add to Up Next", valign=Gtk.Align.CENTER,
                                    sensitive=item.can_add)
                if not item.can_add:
                    button.set_tooltip_text("Its computer is offline")
                button.connect("clicked", lambda b, key=item.key: self._add(b, key))
                row.add_suffix(button)
            self.list.append(row)
        pending = len(data.get("pending_origins") or [])
        if rows:
            self.status.set_text(f"{len(rows)} result{'s' if len(rows) != 1 else ''}"
                                 + (f" - still checking {pending} computer{'s' if pending != 1 else ''}"
                                    if pending else ""))
        else:
            self.status.set_text(f"Nothing in the house matches “{text}”." if text else "")

    def _add(self, button, key: str) -> None:
        button.set_sensitive(False)
        try:
            message = self.owner._portal_queue_action("queue_add_key", {"key": key})
        except portal.PortalRequestError as exc:
            self.owner.toast(exc.message, error=True)
            button.set_sensitive(True)
            return
        self.owner.toast(message or "Added to Up Next")
        button.set_label("Added")


class FindMixin:
    """MainWindow entry points for the Find window."""

    def action_find_house(self) -> None:
        window = getattr(self, "_find_window", None)
        if window is None or not window.get_visible():
            window = FindWindow(self)
            self._find_window = window
        window.present()

    def _house_search(self, text: str) -> dict:
        """Federated search when the mesh library is running, else this computer only."""
        mesh = getattr(self, "_mesh_library", None)
        if mesh is not None:
            return mesh.search_service.search(text, 50)
        indexer = getattr(self, "_library_indexer", None)
        return indexer.search(text, 50) if indexer is not None else {"groups": []}
