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
import queue_metadata
from queue_component import QueueComponent
import room_checkpoint
from queue_prewarm_ui import QueuePrewarmMixin
from queue_row_ui import QueueRowMixin
from music_import_ui import MusicImportMixin
from playlist_ui import PlaylistMixin
from cast_discovery import DeviceDiscoveryMixin

from cast_widgets import ROOM_CHECKPOINT_FILE, save_config, fmt_time, Async


class QueueMixin(PlaylistMixin, MusicImportMixin, QueuePrewarmMixin, QueueRowMixin,
                 DeviceDiscoveryMixin):
    def add_files(self) -> None:
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
        dialog.open_multiple(self, None, self._files_chosen)


    def _files_chosen(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        self._enqueue(playlist_control.natural_order([
            path for index in range(files.get_n_items())
            if (path := files.get_item(index).get_path())]))


    def _file_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            self.set_selection(path)


    def open_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        paths = playlist_control.natural_order(paths)
        first = paths[0]
        self.set_selection(first)
        if len(paths) > 1:
            self._enqueue(paths[1:])
        self.present()


    def open_video(self) -> None:
        dialog = Gtk.FileDialog(title="Choose media")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video and audio files")
        for suffix in sorted(streamer.MEDIA_EXTS):
            video_filter.add_pattern(f"*{suffix}")
        store.append(video_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(video_filter)
        dialog.open(self, None, self._file_chosen)


    def open_recent(self, index: int) -> None:
        recents = self.cfg["recents"]
        if 0 <= index < len(recents):
            path = pathlib.Path(recents[index])
            if path.is_file():
                self.set_selection(str(path))
                self._cast_path(path, None)
            else:
                self.toast("That file has moved or been deleted", error=True)


    def _add_recent(self, path: str) -> None:
        recents = [p for p in self.cfg["recents"] if p != path]
        recents.insert(0, path)
        self.cfg["recents"] = recents[:8]
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())


    def _clear_recents(self) -> None:
        self.cfg["recents"] = []
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())
        self.toast("Recent files cleared")


    def set_selection(self, path: str) -> None:
        if path not in self.queue:
            self.queue.append(path)
            record = getattr(self, "_portal_record_contribution", None)
            if callable(record):
                record(path, "Host", "local")
            self._rebuild_queue()
        index = self.queue.index(path)
        self.selected_index = index
        row = self.queue_list.get_row_at_index(index)
        if row is not None:
            self.queue_list.select_row(row)
        display = (getattr(self, "_portal_queue_display_names", None) or {}).get(path)
        if self.now_playing is None and not self.busy and not self.external and self.session is None:
            self.np_title.set_text(queue_metadata.display_title(path, self._media_cache, display))
        # Re-selecting a queued film while casting must not change active
        # media metadata, its audio/subtitle tracks or the receiver clock.
        if self.session is not None or self.external or self.busy:
            self._refresh_controls()
            return
        if self.session is None and not self.external:
            if self._preview_path == path:
                return  # A row re-selection must not reset the local playhead.
            self._reset_ab_repeat()
            self._unload_local_video()
            self.media = None
            self._update_audio_choices(None)
            self.menu_button.set_menu_model(self._build_menu())
            self._preview_path = path
            self._preview_generation += 1
            self._preview_pending = None
            if getattr(self, "_thumbnail_render_key", None):
                self._refresh_thumbnail_strip(0.0, visible=False)
            self._preview_position = playback_state.start_offset(
                None, (self.cfg.get("positions") or {}).get(path),
            )
            self.preview_picture.set_visible(False)
            self.preview.set_video(queue_metadata.media_title(path, display_name=display), "Reading media duration…")
            self.np_meta.set_text("Inspect the media and scrub to a starting point, then press Cast.")
            self.seekbar.set_state(0.0, 0.0, 0.0)

        generation = self._preview_generation
        fingerprint = queue_metadata.file_fingerprint(path)
        cached = self._media_cache.get(path)
        cache_hit = fingerprint is not None and cached is not None and cached[0] == fingerprint
        if cache_hit:
            self.queue_durations[path] = cached[1].duration
            self.media = cached[1]
            self._update_embedded_choices(self.media)
            self._update_audio_choices(self.media)
            self.menu_button.set_menu_model(self._build_menu())
            self._preview_position = min(
                self._preview_position, max(0.0, self.media.duration - 1.0)
            ) if self.media.duration else 0.0
            self.seekbar.set_state(self._preview_position, self.media.duration, 0.0)
            self._queue_preview(self._preview_position)
        else:
            if fingerprint is None:
                self.queue_durations.pop(path, None)
            self.seekbar.set_state(self._preview_position,
                                   self.queue_durations.get(path, 0.0), 0.0)

        def work():
            return path, streamer.ffprobe(pathlib.Path(path))

        def done(result):
            path_result, media = result
            current_fingerprint = queue_metadata.file_fingerprint(path_result)
            if (fingerprint is None or current_fingerprint != fingerprint
                    or path_result not in self.queue):
                return
            self._media_cache[path_result] = (current_fingerprint, media)
            self.queue_durations[path_result] = media.duration
            if (generation == self._preview_generation
                    and self.now_playing is None and self.session is None
                    and not self.busy and not self.external
                    and self._preview_path == path_result):
                self.media = media
                self._update_embedded_choices(media)
                self._update_audio_choices(media)
                self.menu_button.set_menu_model(self._build_menu())
                duration = media.duration
                self._preview_position = min(self._preview_position, max(0.0, duration - 1.0)) if duration else 0.0
                self.seekbar.set_state(self._preview_position, duration, 0.0)
                self.elapsed_label.set_text(fmt_time(self._preview_position))
                self.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - self._preview_position))}" if duration else "--:--")
                info = " · ".join(bit for bit in (streamer.media_summary(media), fmt_time(duration)) if bit)
                name = (getattr(self, "_portal_queue_display_names", None) or {}).get(path_result)
                title = queue_metadata.media_title(path_result, media, name)
                self.np_title.set_text(title)
                self.preview.set_video(title, info)
                self._queue_preview(self._preview_position)
            self._rebuild_queue()

        def failed(message):
            if (generation == self._preview_generation
                    and self.now_playing is None and self.session is None
                    and not self.busy and not self.external and self._preview_path == path):
                self.np_meta.set_text(f"Cannot inspect media: {message}")
                self.preview.set_video(queue_metadata.media_title(path, display_name=display), "Media inspection failed")
                self.toast(f"Cannot inspect {pathlib.Path(path).name}: {message}", error=True)
            self._console(f"FFprobe failed for {pathlib.Path(path).name}: {message}")

        if not cache_hit:
            Async.run(work, done=done, failed=failed, domain="media")
        else:
            info = " · ".join(bit for bit in (streamer.media_summary(self.media), fmt_time(self.media.duration)) if bit)
            title = queue_metadata.media_title(path, self.media, display)
            self.np_title.set_text(title)
            self.preview.set_video(title, info)
            self.elapsed_label.set_text(fmt_time(self._preview_position))
            self.remaining_label.set_text(f"-{fmt_time(max(0.0, self.media.duration - self._preview_position))}" if self.media.duration else "--:--")
        self._refresh_controls()


    def clear_queue(self) -> None:
        self._cancel_queue_prewarm()
        QueueComponent(self.queue).clear()
        self.selected_index = None
        self._retire_unqueued_preview()
        self._rebuild_queue()
        self.toast("Queue cleared")


    def _enqueue(self, paths: list[str]) -> None:
        added = 0
        for path in QueueComponent(self.queue).add(paths):
            record = getattr(self, "_portal_record_contribution", None)
            if callable(record):
                record(path, "Host", "local")
            added += 1
            fingerprint.KEYS.get(path)         # warm the content key in the background
        if not added:
            return
        self._rebuild_queue()
        self.toast(f"Added {added} media item{'s' if added != 1 else ''} to the queue")
        if (self.now_playing is None and self.selected_index is None and self.queue
                and not self.busy and self.session is None and not self.external):
            self.set_selection(self.queue[0])

        duration_paths = self._queue_duration_paths(paths)

        def probe():
            return queue_metadata.inspect(
                duration_paths, lambda path: streamer.ffprobe(pathlib.Path(path)).duration,
            )

        def done(durations):
            queue_metadata.publish(self.queue_durations, self.queue, durations)
            self._rebuild_queue()

        if duration_paths:
            Async.run(probe, done=done, domain="media", valid=lambda: not self._closing)


    def _remove_queue(self, index: int) -> None:
        removed, self.selected_index = QueueComponent(self.queue).remove(index, self.selected_index)
        if removed is not None:
            if removed == self.now_playing and not (
                self.session and self.session.state is not None
            ):
                self.now_playing = None
            self._retire_unqueued_preview()
            self._rebuild_queue()
            self._prewarm_queue_media()


    def _rebuild_queue(self) -> None:
        prune = getattr(self, "_portal_prune_queue_provenance", None)
        if callable(prune):
            prune()
        # GTK emits row-selected(None) while clearing; preserve the source
        # row index so a rebuild does not change the file selected for casting.
        selected = (
            self.queue[self.selected_index]
            if self.selected_index is not None and 0 <= self.selected_index < len(self.queue)
            else None
        )
        while self.queue_list.get_row_at_index(0) is not None:
            self.queue_list.remove(self.queue_list.get_row_at_index(0))
        for index, path in enumerate(self.queue):
            self.queue_list.append(self._queue_row(index, path))
        self.selected_index = self.queue.index(selected) if selected in self.queue else None
        if self.selected_index is not None:
            row = self.queue_list.get_row_at_index(self.selected_index)
            if row is not None and self._queue_row_matches(row):
                self.queue_list.select_row(row)
        self._refresh_queue_visibility()
        self._refresh_controls()
        self._save_room_checkpoint()


    def _save_room_checkpoint(self) -> None:
        if (getattr(getattr(self, "app", None), "selftest", False)
                or getattr(self, "_portal", None) is None):
            return
        checkpoint = getattr(self, "_room_checkpoint_file", ROOM_CHECKPOINT_FILE)
        items = tuple(self.queue)
        names = room_checkpoint.queue_display_names(items, getattr(self, "_portal_queue_display_names", {}))
        if (items == getattr(self, "_room_checkpoint_last", None)
                and names == getattr(self, "_room_checkpoint_names_last", ())):
            return
        if not items and not checkpoint.exists():
            return
        try:
            room_checkpoint.write_checkpoint(checkpoint, items, display_names=dict(names))
        except (OSError, ValueError) as exc:
            if not getattr(self, "_room_checkpoint_error_shown", False):
                self._room_checkpoint_error_shown = True
                self.toast("Shared room recovery could not be saved", error=True)
                self._console(f"Room queue checkpoint failed: {exc}")
            return
        self._room_checkpoint_last = items
        self._room_checkpoint_names_last = names


    def _refresh_queue_visibility(self) -> None:
        query = self.queue_search.get_text()
        # Use the same rendered rows and predicate as GTK's filter. No
        # metadata re-probe or filesystem access on each keystroke.
        visible = [
            path for index, path in enumerate(self.queue)
            if (row := self.queue_list.get_row_at_index(index)) is not None
            and self._queue_row_matches(row)
        ] if query.strip() else self.queue
        has_queue = bool(self.queue)
        self.queue_search.set_visible(has_queue)
        self.queue_empty.set_visible(not has_queue)
        self.queue_no_matches.set_visible(has_queue and not visible)
        self.queue_scroller.set_visible(bool(visible))
        self.queue_summary.set_visible(has_queue)
        if has_queue:
            total = sum(self.queue_durations.get(p, 0.0) or 0.0 for p in visible)
            known = all(self.queue_durations.get(p) for p in visible)
            count = len(visible)
            label = f"{count} item{'s' if count != 1 else ''}"
            if query.strip():
                label += f" of {len(self.queue)} in queue"
            if total > 0:
                label += f" · {fmt_time(total)}{'' if known else '+'}"
            self.queue_summary.set_text(label)


    def _on_queue_search(self, _entry) -> None:
        self.queue_list.invalidate_filter()
        self._refresh_queue_visibility()


    def _on_queue_selected(self, _list, row) -> None:
        if row is None and self.queue_search.get_text().strip():
            return  # A hidden row must not change playback selection.
        selected_path = getattr(row, "source_path", None) if row is not None else None
        self.selected_index = (
            self.queue.index(selected_path) if selected_path in self.queue else None
        )
        if (self.selected_index is not None
                and 0 <= self.selected_index < len(self.queue)
                and self.session is None and not self.external and not self.busy):
            path = self.queue[self.selected_index]
            if path != self._preview_path:
                # Delay to avoid mutating a Gtk.ListBox during its selection signal.
                def select_if_current():
                    index = self.selected_index
                    if (not self._closing and not self.busy and self.session is None
                            and not self.external and index is not None
                            and 0 <= index < len(self.queue) and self.queue[index] == path
                            and path != self._preview_path):
                        self.set_selection(path)
                    return False

                GLib.idle_add(select_if_current)


    def _on_queue_activated(self, _list, row) -> None:
        path = getattr(row, "source_path", None) if row is not None else None
        if path in self.queue:
            # GTK filtering can change visual row positions. Cast by stable
            # file identity, never by a potentially filtered row index.
            self._cast_path(pathlib.Path(path), None)


    def _retire_unqueued_preview(self) -> None:
        """Retire deleted local media without touching an owned TV session."""
        if (self.session is not None or self.external or
                self._preview_path is None or self._preview_path in self.queue):
            return
        self._preview_generation += 1
        self._reset_ab_repeat()
        self._preview_pending = None
        self._unload_local_video()
        self._preview_path = None
        self._preview_position = 0.0
        if getattr(self, "_thumbnail_render_key", None):
            self._refresh_thumbnail_strip(0.0, visible=False)
        self.preview_picture.set_visible(False)
        self.media = None
        self._update_audio_choices(None)
        self.embedded_dropdown.set_visible(False)
        self.seekbar.set_state(0.0, 0.0, 0.0)
        self.elapsed_label.set_text("00:00")
        self.remaining_label.set_text("--:--")
        self.np_title.set_text("Ready to cast")
        self.np_meta.set_text("Open a film to inspect and cast it")
