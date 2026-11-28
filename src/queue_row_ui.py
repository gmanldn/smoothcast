"""Desktop queue rows and input for changing the playback order."""
from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GObject, Gtk, Pango

import playlist_control
import room_events
import secrets
import queue_metadata
from cast_widgets import fmt_time


class QueueRowController:
    """Composition replacement for QueueRowMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _move_queue(self, index: int, delta: int) -> bool:
        w = self.w
        target = index + delta
        if w.busy or w._closing or index == target:
            return False
        if not (0 <= index < len(w.queue) and 0 <= target < len(w.queue)):
            return False
        w.selected_index = playlist_control.selection_after_move(
            w.selected_index, index, target,
        )
        room_events.store_for(w).submit(secrets.token_hex(8), "move", index, target)
        w._rebuild_queue()
        w._prewarm_queue_media()
        return True

    def _drop_queue_row(self, _drop, source, _x, y, destination) -> bool:
        w = self.w
        if (source.get_parent() != w.queue_list
                or destination.get_parent() != w.queue_list):
            return False
        index = source.get_index()
        # The row midpoint gives a boundary in the full queue, even when filtered.
        boundary = destination.get_index() + (y >= destination.get_height() / 2)
        target = boundary - (index < boundary)
        return w._move_queue(index, target - index)

    def _queue_row(self, index: int, path: str) -> Gtk.ListBoxRow:
        w = self.w
        row = Gtk.ListBoxRow()
        row.source_path = path  # Private identity; never put a filesystem path in a tooltip.
        row.add_css_class("queue-row")
        if path == w.now_playing:
            row.add_css_class("current")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        index_label = Gtk.Label(label=str(index + 1), ellipsize=Pango.EllipsizeMode.END)
        index_label.add_css_class("dim-label")
        index_label.add_css_class("caption")
        index_label.set_width_chars(2)
        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.set_tooltip_text("Drag to reorder the playback queue")
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)

        def prepare_drag(_drag, _x, _y):
            if w.busy or w._closing:
                return None
            return Gdk.ContentProvider.new_for_value(GObject.Value(Gtk.ListBoxRow, row))

        drag.connect("prepare", prepare_drag)
        handle.add_controller(drag)
        drop = Gtk.DropTarget.new(Gtk.ListBoxRow, Gdk.DragAction.MOVE)
        drop.connect("drop", w._drop_queue_row, row)
        row.add_controller(drop)
        display_name = getattr(w, "_portal_queue_display_names", {}).get(path)
        display_title = queue_metadata.display_title(path, w._media_cache, display_name)
        row.display_title = display_title
        row.set_tooltip_text(display_title)
        title = Gtk.Label(label=display_title, xalign=0.0, hexpand=True, ellipsize=3)
        title.add_css_class("queue-title")
        # GTK ListBoxRow needs its own accessible name. Do not announce the
        # tooltip/source path (which may expose the user's private folders).
        playback_state = "Now playing" if path == w.now_playing else "Queued"
        row.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [f"{display_title}, {index + 1} of {len(w.queue)}, {playback_state}"],
        )
        duration = w.queue_durations.get(path)
        duration_label = Gtk.Label(label=fmt_time(duration) if duration else "", ellipsize=Pango.EllipsizeMode.END)
        duration_label.add_css_class("dim-label")
        duration_label.add_css_class("caption")
        up = w._icon_button("go-up-symbolic", "Move up", "flat", lambda i=index: w._move_queue(i, -1))
        down = w._icon_button("go-down-symbolic", "Move down", "flat", lambda i=index: w._move_queue(i, 1))
        remove = w._icon_button("window-close-symbolic", "Remove", "flat", lambda i=index: w._remove_queue(i))
        up.set_sensitive(index > 0)
        down.set_sensitive(index + 1 < len(w.queue))
        # Reorder arrows appear for the selected or hovered row only, which
        # leaves the title the full width (dragging the handle still works).
        row.move_buttons = (up, down)
        for button in row.move_buttons:
            button.set_visible(False)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_a: w._show_queue_moves(row, True))
        hover.connect("leave", lambda *_a: w._show_queue_moves(row, False))
        row.add_controller(hover)
        for widget in (handle, index_label, title, duration_label, up, down, remove):
            box.append(widget)
        row.set_child(box)
        return row


    @staticmethod
    def _show_queue_moves(row, hovering: bool) -> None:
        visible = hovering or row.is_selected()
        for button in getattr(row, "move_buttons", ()):
            button.set_visible(visible)


    def _sync_queue_moves(self, _listbox=None, _selected=None) -> None:
        """Keep the reorder arrows in step with the selected row."""
        w = self.w
        index = 0
        while (row := w.queue_list.get_row_at_index(index)) is not None:
            w._show_queue_moves(row, False)
            index += 1


    def _queue_row_matches(self, row) -> bool:
        w = self.w
        return playlist_control.matches_query(
            getattr(row, "source_path", "") or "", w.queue_search.get_text(),
            display_title=getattr(row, "display_title", ""),
        )

    @classmethod
    def install(cls, window) -> "QueueRowController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in QUEUE_ROW_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


QUEUE_ROW_CONTROLLER_METHODS = ('_move_queue', '_drop_queue_row', '_queue_row', '_show_queue_moves', '_sync_queue_moves', '_queue_row_matches')
