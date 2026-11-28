#!/usr/bin/env python3
"""Queue and file opening; receiver discovery lives in cast_discovery."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, GLib, Gtk
import pathlib


import fingerprint


import streamer

import playback_state

import playlist_control
import room_events
import secrets
import queue_metadata
from queue_component import QueueComponent
import room_checkpoint

from cast_widgets import ROOM_CHECKPOINT_FILE, save_config, fmt_time, Async


class QueueController:
    """Composition replacement for QueueMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def add_files(self) -> None:
        w = self.w
        dialog = Gtk.FileDialog(title="Add media to the queue")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video and audio files")
        for suffix in sorted(streamer.MEDIA_EXTS):
            video_filter.add_pattern(f"*{suffix}")
        store.append(video_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        store.append(all_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(video_filter)
        dialog.open_multiple(w, None, w._files_chosen)


    def _files_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        w._enqueue(playlist_control.natural_order([
            path for index in range(files.get_n_items())
            if (path := files.get_item(index).get_path())]))


    def _file_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            w.set_selection(path)


    def open_paths(self, paths: list[str]) -> None:
        w = self.w
        if not paths:
            return
        paths = playlist_control.natural_order(paths)
        first = paths[0]
        w.set_selection(first)
        if len(paths) > 1:
            w._enqueue(paths[1:])
        w.present()


    def open_video(self) -> None:
        w = self.w
        dialog = Gtk.FileDialog(title="Choose media")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video and audio files")
        for suffix in sorted(streamer.MEDIA_EXTS):
            video_filter.add_pattern(f"*{suffix}")
        store.append(video_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(video_filter)
        dialog.open(w, None, w._file_chosen)


    def open_recent(self, index: int) -> None:
        w = self.w
        recents = w.cfg["recents"]
        if 0 <= index < len(recents):
            path = pathlib.Path(recents[index])
            if path.is_file():
                w.set_selection(str(path))
                w._cast_path(path, None)
            else:
                w.toast("That file has moved or been deleted", error=True)


    def _add_recent(self, path: str) -> None:
        w = self.w
        recents = [p for p in w.cfg["recents"] if p != path]
        recents.insert(0, path)
        w.cfg["recents"] = recents[:8]
        save_config(w.cfg)
        w.menu_button.set_menu_model(w._build_menu())


    def _clear_recents(self) -> None:
        w = self.w
        w.cfg["recents"] = []
        save_config(w.cfg)
        w.menu_button.set_menu_model(w._build_menu())
        w.toast("Recent files cleared")


    def set_selection(self, path: str) -> None:
        w = self.w
        if path not in w.queue:
            w.queue.append(path)
            record = getattr(w, "_portal_record_contribution", None)
            if callable(record):
                record(path, "Host", "local")
            w._rebuild_queue()
        index = w.queue.index(path)
        w.selected_index = index
        row = w.queue_list.get_row_at_index(index)
        if row is not None:
            w.queue_list.select_row(row)
        display = (getattr(w, "_portal_queue_display_names", None) or {}).get(path)
        if w.now_playing is None and not w.busy and not w.external and w.session is None:
            w.np_title.set_text(queue_metadata.display_title(path, w._media_cache, display))
        # Re-selecting a queued film while casting must not change active
        # media metadata, its audio/subtitle tracks or the receiver clock.
        if w.session is not None or w.external or w.busy:
            w._refresh_controls()
            return
        if w.session is None and not w.external:
            if w._preview_path == path:
                return  # A row re-selection must not reset the local playhead.
            w._reset_ab_repeat()
            w._unload_local_video()
            w.media = None
            w._update_audio_choices(None)
            w.menu_button.set_menu_model(w._build_menu())
            w._preview_path = path
            w._preview_generation += 1
            w._preview_pending = None
            if getattr(w, "_thumbnail_render_key", None):
                w._refresh_thumbnail_strip(0.0, visible=False)
            w._preview_position = playback_state.start_offset(
                None, (w.cfg.get("positions") or {}).get(path),
            )
            w.preview_picture.set_visible(False)
            w.preview.set_video(queue_metadata.media_title(path, display_name=display), "Reading media duration…")
            w.np_meta.set_text("Inspect the media and scrub to a starting point, then press Cast.")
            w.seekbar.set_state(0.0, 0.0, 0.0)

        generation = w._preview_generation
        fingerprint = queue_metadata.file_fingerprint(path)
        cached = w._media_cache.get(path)
        cache_hit = fingerprint is not None and cached is not None and cached[0] == fingerprint
        if cache_hit:
            w.queue_durations[path] = cached[1].duration
            w.media = cached[1]
            w._update_embedded_choices(w.media)
            w._update_audio_choices(w.media)
            w.menu_button.set_menu_model(w._build_menu())
            w._preview_position = min(
                w._preview_position, max(0.0, w.media.duration - 1.0)
            ) if w.media.duration else 0.0
            w.seekbar.set_state(w._preview_position, w.media.duration, 0.0)
            w._queue_preview(w._preview_position)
        else:
            if fingerprint is None:
                w.queue_durations.pop(path, None)
            w.seekbar.set_state(w._preview_position,
                                   w.queue_durations.get(path, 0.0), 0.0)

        def work():
            return path, streamer.ffprobe(pathlib.Path(path))

        def done(result):
            path_result, media = result
            current_fingerprint = queue_metadata.file_fingerprint(path_result)
            if (fingerprint is None or current_fingerprint != fingerprint
                    or path_result not in w.queue):
                return
            w._media_cache[path_result] = (current_fingerprint, media)
            w.queue_durations[path_result] = media.duration
            if (generation == w._preview_generation
                    and w.now_playing is None and w.session is None
                    and not w.busy and not w.external
                    and w._preview_path == path_result):
                w.media = media
                w._update_embedded_choices(media)
                w._update_audio_choices(media)
                w.menu_button.set_menu_model(w._build_menu())
                duration = media.duration
                w._preview_position = min(w._preview_position, max(0.0, duration - 1.0)) if duration else 0.0
                w.seekbar.set_state(w._preview_position, duration, 0.0)
                w.elapsed_label.set_text(fmt_time(w._preview_position))
                w.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - w._preview_position))}" if duration else "--:--")
                info = " · ".join(bit for bit in (streamer.media_summary(media), fmt_time(duration)) if bit)
                name = (getattr(w, "_portal_queue_display_names", None) or {}).get(path_result)
                title = queue_metadata.media_title(path_result, media, name)
                w.np_title.set_text(title)
                w.preview.set_video(title, info)
                w._queue_preview(w._preview_position)
            w._rebuild_queue()

        def failed(message):
            if (generation == w._preview_generation
                    and w.now_playing is None and w.session is None
                    and not w.busy and not w.external and w._preview_path == path):
                w.np_meta.set_text(f"Cannot inspect media: {message}")
                w.preview.set_video(queue_metadata.media_title(path, display_name=display), "Media inspection failed")
                w.toast(f"Cannot inspect {pathlib.Path(path).name}: {message}", error=True)
            w._console(f"FFprobe failed for {pathlib.Path(path).name}: {message}")

        if not cache_hit:
            Async.run(work, done=done, failed=failed, domain="media")
        else:
            info = " · ".join(bit for bit in (streamer.media_summary(w.media), fmt_time(w.media.duration)) if bit)
            title = queue_metadata.media_title(path, w.media, display)
            w.np_title.set_text(title)
            w.preview.set_video(title, info)
            w.elapsed_label.set_text(fmt_time(w._preview_position))
            w.remaining_label.set_text(f"-{fmt_time(max(0.0, w.media.duration - w._preview_position))}" if w.media.duration else "--:--")
        w._refresh_controls()


    def clear_queue(self) -> None:
        w = self.w
        w._cancel_queue_prewarm()
        room_events.store_for(w).submit(secrets.token_hex(8), "clear")
        w.selected_index = None
        w._retire_unqueued_preview()
        w._rebuild_queue()
        w.toast("Queue cleared")


    def _enqueue(self, paths: list[str]) -> None:
        w = self.w
        added = 0
        before = set(w.queue)
        events = room_events.store_for(w).submit(secrets.token_hex(8), "add", paths)
        for path in [p for e in events for p in e.data if p not in before]:
            record = getattr(w, "_portal_record_contribution", None)
            if callable(record):
                record(path, "Host", "local")
            added += 1
            fingerprint.KEYS.get(path)         # warm the content key in the background
        if not added:
            return
        w._rebuild_queue()
        w.toast(f"Added {added} media item{'s' if added != 1 else ''} to the queue")
        if (w.now_playing is None and w.selected_index is None and w.queue
                and not w.busy and w.session is None and not w.external):
            w.set_selection(w.queue[0])

        duration_paths = w._queue_duration_paths(paths)

        def probe():
            return queue_metadata.inspect(
                duration_paths, lambda path: streamer.ffprobe(pathlib.Path(path)).duration,
            )

        def done(durations):
            queue_metadata.publish(w.queue_durations, w.queue, durations)
            w._rebuild_queue()

        if duration_paths:
            Async.run(probe, done=done, domain="media", valid=lambda: not w._closing)


    def _remove_queue(self, index: int) -> None:
        w = self.w
        removed = w.queue[index] if 0 <= index < len(w.queue) else None
        if removed is not None:
            room_events.store_for(w).submit(secrets.token_hex(8), "remove", index)
            w.selected_index = playlist_control.selection_after_remove(
                w.selected_index, index, len(w.queue))
            if removed == w.now_playing and not (
                w.session and w.session.state is not None
            ):
                w.now_playing = None
            w._retire_unqueued_preview()
            w._rebuild_queue()
            w._prewarm_queue_media()


    def _rebuild_queue(self) -> None:
        w = self.w
        prune = getattr(w, "_portal_prune_queue_provenance", None)
        if callable(prune):
            prune()
        # GTK emits row-selected(None) while clearing; preserve the source
        # row index so a rebuild does not change the file selected for casting.
        selected = (
            w.queue[w.selected_index]
            if w.selected_index is not None and 0 <= w.selected_index < len(w.queue)
            else None
        )
        while w.queue_list.get_row_at_index(0) is not None:
            w.queue_list.remove(w.queue_list.get_row_at_index(0))
        for index, path in enumerate(w.queue):
            w.queue_list.append(w._queue_row(index, path))
        w.selected_index = w.queue.index(selected) if selected in w.queue else None
        if w.selected_index is not None:
            row = w.queue_list.get_row_at_index(w.selected_index)
            if row is not None and w._queue_row_matches(row):
                w.queue_list.select_row(row)
        w._refresh_queue_visibility()
        w._refresh_controls()
        w._save_room_checkpoint()


    def _save_room_checkpoint(self) -> None:
        w = self.w
        if (getattr(getattr(w, "app", None), "selftest", False)
                or getattr(w, "_portal", None) is None):
            return
        checkpoint = getattr(w, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        items = tuple(w.queue)
        names = room_checkpoint.queue_display_names(items, getattr(w, "_portal_queue_display_names", {}))
        if (items == getattr(w, "_room_checkpoint_last", None)
                and names == getattr(w, "_room_checkpoint_names_last", ())):
            return
        if not items and not checkpoint.exists():
            return
        try:
            room_checkpoint.write_checkpoint(checkpoint, items, display_names=dict(names))
        except (OSError, ValueError) as exc:
            if not getattr(w, "_room_checkpoint_error_shown", False):
                w._room_checkpoint_error_shown = True
                w.toast("Shared room recovery could not be saved", error=True)
                w._console(f"Room queue checkpoint failed: {exc}")
            return
        w._room_checkpoint_last = items
        w._room_checkpoint_names_last = names


    def _refresh_queue_visibility(self) -> None:
        w = self.w
        query = w.queue_search.get_text()
        # Use the same rendered rows and predicate as GTK's filter. No
        # metadata re-probe or filesystem access on each keystroke.
        visible = [
            path for index, path in enumerate(w.queue)
            if (row := w.queue_list.get_row_at_index(index)) is not None
            and w._queue_row_matches(row)
        ] if query.strip() else w.queue
        has_queue = bool(w.queue)
        w.queue_search.set_visible(has_queue)
        w.queue_empty.set_visible(not has_queue)
        w.queue_no_matches.set_visible(has_queue and not visible)
        w.queue_scroller.set_visible(bool(visible))
        w.queue_summary.set_visible(has_queue)
        if has_queue:
            total, known = QueueComponent.total_duration(w.queue_durations, visible)
            count = len(visible)
            label = f"{count} item{'s' if count != 1 else ''}"
            if query.strip():
                label += f" of {len(w.queue)} in queue"
            if total > 0:
                label += f" · {fmt_time(total)}{'' if known else '+'}"
            w.queue_summary.set_text(label)


    def _on_queue_search(self, _entry) -> None:
        w = self.w
        w.queue_list.invalidate_filter()
        w._refresh_queue_visibility()


    def _on_queue_selected(self, _list, row) -> None:
        w = self.w
        if row is None and w.queue_search.get_text().strip():
            return  # A hidden row must not change playback selection.
        selected_path = getattr(row, "source_path", None) if row is not None else None
        w.selected_index = (
            w.queue.index(selected_path) if selected_path in w.queue else None
        )
        if (w.selected_index is not None
                and 0 <= w.selected_index < len(w.queue)
                and w.session is None and not w.external and not w.busy):
            path = w.queue[w.selected_index]
            if path != w._preview_path:
                # Delay to avoid mutating a Gtk.ListBox during its selection signal.
                def select_if_current():
                    index = w.selected_index
                    if (not w._closing and not w.busy and w.session is None
                            and not w.external and index is not None
                            and 0 <= index < len(w.queue) and w.queue[index] == path
                            and path != w._preview_path):
                        w.set_selection(path)
                    return False

                GLib.idle_add(select_if_current)


    def _on_queue_activated(self, _list, row) -> None:
        w = self.w
        path = getattr(row, "source_path", None) if row is not None else None
        if path in w.queue:
            # GTK filtering can change visual row positions. Cast by stable
            # file identity, never by a potentially filtered row index.
            w._cast_path(pathlib.Path(path), None)


    def _retire_unqueued_preview(self) -> None:
        """Retire deleted local media without touching an owned TV session."""
        w = self.w
        if (w.session is not None or w.external or
                w._preview_path is None or w._preview_path in w.queue):
            return
        w._preview_generation += 1
        w._reset_ab_repeat()
        w._preview_pending = None
        w._unload_local_video()
        w._preview_path = None
        w._preview_position = 0.0
        if getattr(w, "_thumbnail_render_key", None):
            w._refresh_thumbnail_strip(0.0, visible=False)
        w.preview_picture.set_visible(False)
        w.media = None
        w._update_audio_choices(None)
        w.embedded_dropdown.set_visible(False)
        w.seekbar.set_state(0.0, 0.0, 0.0)
        w.elapsed_label.set_text("00:00")
        w.remaining_label.set_text("--:--")
        w.np_title.set_text("Ready to cast")
        w.np_meta.set_text("Open a film to inspect and cast it")

    @classmethod
    def install(cls, window) -> "QueueController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in QUEUE_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


QUEUE_CONTROLLER_METHODS = ('add_files', '_files_chosen', '_file_chosen', 'open_paths', 'open_video', 'open_recent', '_add_recent', '_clear_recents', 'set_selection', 'clear_queue', '_enqueue', '_remove_queue', '_rebuild_queue', '_save_room_checkpoint', '_refresh_queue_visibility', '_on_queue_search', '_on_queue_selected', '_on_queue_activated', '_retire_unqueued_preview')
