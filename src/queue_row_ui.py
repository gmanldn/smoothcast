"""Desktop queue rows and input for changing the playback order."""
from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GObject, Gtk, Pango

import playlist_control
import queue_metadata
from cast_widgets import fmt_time


class QueueRowMixin:
    def _move_queue(self, index: int, delta: int) -> bool:
        target = index + delta
        if self.busy or self._closing or index == target:
            return False
        if not (0 <= index < len(self.queue) and 0 <= target < len(self.queue)):
            return False
        self.selected_index = playlist_control.selection_after_move(
            self.selected_index, index, target,
        )
        self.queue.insert(target, self.queue.pop(index))
        self._rebuild_queue()
        self._prewarm_queue_media()
        return True

    def _drop_queue_row(self, _drop, source, _x, y, destination) -> bool:
        if (source.get_parent() != self.queue_list
                or destination.get_parent() != self.queue_list):
            return False
        index = source.get_index()
        # The row midpoint gives a boundary in the full queue, even when filtered.
        boundary = destination.get_index() + (y >= destination.get_height() / 2)
        target = boundary - (index < boundary)
        return self._move_queue(index, target - index)

    def _queue_row(self, index: int, path: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_tooltip_text(path)  # Stable source path for GTK filtering.
        row.add_css_class("queue-row")
        if path == self.now_playing:
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
            if self.busy or self._closing:
                return None
            return Gdk.ContentProvider.new_for_value(GObject.Value(Gtk.ListBoxRow, row))

        drag.connect("prepare", prepare_drag)
        handle.add_controller(drag)
        drop = Gtk.DropTarget.new(Gtk.ListBoxRow, Gdk.DragAction.MOVE)
        drop.connect("drop", self._drop_queue_row, row)
        row.add_controller(drop)
        title = Gtk.Label(label=queue_metadata.display_title(path, self._media_cache), xalign=0.0, hexpand=True, ellipsize=3)
        title.add_css_class("queue-title")
        duration = self.queue_durations.get(path)
        duration_label = Gtk.Label(label=fmt_time(duration) if duration else "", ellipsize=Pango.EllipsizeMode.END)
        duration_label.add_css_class("dim-label")
        duration_label.add_css_class("caption")
        up = self._icon_button("go-up-symbolic", "Move up", "flat", lambda i=index: self._move_queue(i, -1))
        down = self._icon_button("go-down-symbolic", "Move down", "flat", lambda i=index: self._move_queue(i, 1))
        remove = self._icon_button("window-close-symbolic", "Remove", "flat", lambda i=index: self._remove_queue(i))
        up.set_sensitive(index > 0)
        down.set_sensitive(index + 1 < len(self.queue))
        # Reorder arrows appear for the selected or hovered row only, which
        # leaves the title the full width (dragging the handle still works).
        row.move_buttons = (up, down)
        for button in row.move_buttons:
            button.set_visible(False)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda *_a: self._show_queue_moves(row, True))
        hover.connect("leave", lambda *_a: self._show_queue_moves(row, False))
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
        index = 0
        while (row := self.queue_list.get_row_at_index(index)) is not None:
            self._show_queue_moves(row, False)
            index += 1


    def _queue_row_matches(self, row) -> bool:
        return playlist_control.matches_query(
            row.get_tooltip_text() or "", self.queue_search.get_text()
        )
