#!/usr/bin/env python3
"""Queue, file opening and device discovery/target selection."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, GLib, Gtk
import pathlib

from utils import pretty_title
import time

import castctl

import dlna

import streamer

import playback_state

import cast_targets
import playlist_control
import queue_metadata

from cast_widgets import save_config, fmt_time, Async


class QueueMixin:
    def add_files(self) -> None:
        dialog = Gtk.FileDialog(title="Add videos to the queue")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video files")
        for pattern in ("*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm", "*.m4v", "*.ts", "*.mpeg", "*.mpg", "*.wmv"):
            video_filter.add_pattern(pattern)
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
        paths = []
        for index in range(files.get_n_items()):
            gfile = files.get_item(index)
            path = gfile.get_path()
            if path:
                paths.append(path)
        self._enqueue(paths)


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
        first = paths[0]
        self.set_selection(first)
        if len(paths) > 1:
            self._enqueue(paths[1:])
        self.present()


    def open_video(self) -> None:
        dialog = Gtk.FileDialog(title="Choose a video")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video files")
        for pattern in ("*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm", "*.m4v", "*.ts", "*.mpeg", "*.mpg", "*.wmv"):
            video_filter.add_pattern(pattern)
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
            self._rebuild_queue()
        index = self.queue.index(path)
        self.selected_index = index
        row = self.queue_list.get_row_at_index(index)
        if row is not None:
            self.queue_list.select_row(row)
        if self.now_playing is None and not self.busy:
            self.np_title.set_text(pathlib.Path(path).name)
        # Re-selecting a queued film while casting must not change active
        # media metadata, its audio/subtitle tracks or the receiver clock.
        if self.session is not None or self.external or self.busy:
            self._refresh_controls()
            return
        if self.session is None and not self.external:
            if self._preview_path == path:
                return  # A row re-selection must not reset the local playhead.
            self._unload_local_video()
            self.media = None
            self._update_audio_choices(None)
            self._preview_path = path
            self._preview_generation += 1
            self._preview_pending = None
            self._preview_position = playback_state.start_offset(
                None, (self.cfg.get("positions") or {}).get(path),
            )
            self.preview_picture.set_visible(False)
            self.preview.set_video(pretty_title(path), "Reading film duration…")
            self.np_meta.set_text("Inspect the film and scrub to a starting point, then press Cast.")
            self.seekbar.set_state(0.0, 0.0, 0.0)

        generation = self._preview_generation
        try:
            info = pathlib.Path(path).stat()
            fingerprint = (info.st_size, info.st_mtime_ns)
        except OSError:
            fingerprint = None
        cached = self._media_cache.get(path)
        if cached is not None and cached[0] == fingerprint:
            # Duration and codec details do not need to be re-probed when a
            # film is reselected; the stat fingerprint invalidates changed files.
            self.queue_durations[path] = cached[1].duration
            self.media = cached[1]
            self._update_embedded_choices(self.media)
            self._update_audio_choices(self.media)
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
            try:
                info = pathlib.Path(path_result).stat()
                current_fingerprint = (info.st_size, info.st_mtime_ns)
            except OSError:
                current_fingerprint = None
            if current_fingerprint is not None:
                self._media_cache[path_result] = (current_fingerprint, media)
            self.queue_durations[path_result] = media.duration
            if (generation == self._preview_generation
                    and self.now_playing is None and self.session is None
                    and not self.external and self._preview_path == path_result):
                self.media = media
                self._update_embedded_choices(media)
                self._update_audio_choices(media)
                duration = media.duration
                self._preview_position = min(self._preview_position, max(0.0, duration - 1.0)) if duration else 0.0
                self.seekbar.set_state(self._preview_position, duration, 0.0)
                self.elapsed_label.set_text(fmt_time(self._preview_position))
                self.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - self._preview_position))}" if duration else "--:--")
                info = " · ".join(x for x in (media.resolution, media.vcodec, fmt_time(duration)) if x)
                self.preview.set_video(pretty_title(path_result), info)
                self._queue_preview(self._preview_position)
            self._rebuild_queue()

        def failed(message):
            if (generation == self._preview_generation
                    and self.session is None and self._preview_path == path):
                self.np_meta.set_text(f"Cannot inspect film: {message}")
                self.preview.set_video(pretty_title(path), "Media inspection failed")
                self.toast(f"Cannot inspect {pathlib.Path(path).name}: {message}", error=True)
            self._console(f"FFprobe failed for {pathlib.Path(path).name}: {message}")

        if cached is None or cached[0] != fingerprint:
            Async.run(work, done=done, failed=failed, domain="media")
        else:
            self.preview.set_video(pretty_title(path), " · ".join(
                x for x in (self.media.resolution, self.media.vcodec, fmt_time(self.media.duration)) if x
            ))
            self.elapsed_label.set_text(fmt_time(self._preview_position))
            self.remaining_label.set_text(f"-{fmt_time(max(0.0, self.media.duration - self._preview_position))}" if self.media.duration else "--:--")
        self._refresh_controls()


    def clear_queue(self) -> None:
        self.queue.clear()
        self.selected_index = None
        self._retire_unqueued_preview()
        self._rebuild_queue()
        self.toast("Queue cleared")


    def _enqueue(self, paths: list[str]) -> None:
        added = 0
        for path in paths:
            if path not in self.queue:
                self.queue.append(path)
                added += 1
        if not added:
            return
        self._rebuild_queue()
        self.toast(f"Added {added} video{'s' if added != 1 else ''} to the queue")
        if self.now_playing is None and self.selected_index is None and self.queue:
            self.set_selection(self.queue[0])

        missing = tuple(path for path in paths if path not in self.queue_durations)

        def probe():
            return queue_metadata.inspect(
                missing, lambda path: streamer.ffprobe(pathlib.Path(path)).duration,
            )

        def done(durations):
            queue_metadata.publish(self.queue_durations, self.queue, durations)
            self._rebuild_queue()

        Async.run(probe, done=done, domain="media", valid=lambda: not self._closing)


    def _remove_queue(self, index: int) -> None:
        if 0 <= index < len(self.queue):
            removed = self.queue.pop(index)
            self.selected_index = playlist_control.selection_after_remove(
                self.selected_index, index, len(self.queue),
            )
            if removed == self.now_playing and not (
                self.session and self.session.state is not None
            ):
                self.now_playing = None
            self._retire_unqueued_preview()
            self._rebuild_queue()


    def _move_queue(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= index < len(self.queue) and 0 <= target < len(self.queue):
            self.selected_index = playlist_control.selection_after_move(
                self.selected_index, index, target,
            )
            self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
            self._rebuild_queue()


    def _rebuild_queue(self) -> None:
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


    def _refresh_queue_visibility(self) -> None:
        query = self.queue_search.get_text()
        visible = [p for p in self.queue if playlist_control.matches_query(p, query)]
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
            label = f"{count} video{'s' if count != 1 else ''}"
            if query.strip():
                label += f" of {len(self.queue)} in queue"
            if total > 0:
                label += f" · {fmt_time(total)}{'' if known else '+'}"
            self.queue_summary.set_text(label)


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
        index_label = Gtk.Label(label=str(index + 1))
        index_label.add_css_class("dim-label")
        index_label.add_css_class("caption")
        index_label.set_width_chars(2)
        title = Gtk.Label(label=pathlib.Path(path).name, xalign=0.0, hexpand=True, ellipsize=3)
        title.add_css_class("queue-title")
        title.set_tooltip_text(path)
        duration = self.queue_durations.get(path)
        duration_label = Gtk.Label(label=fmt_time(duration) if duration else "")
        duration_label.add_css_class("dim-label")
        duration_label.add_css_class("caption")
        up = self._icon_button("go-up-symbolic", "Move up", "flat", lambda i=index: self._move_queue(i, -1))
        down = self._icon_button("go-down-symbolic", "Move down", "flat", lambda i=index: self._move_queue(i, 1))
        remove = self._icon_button("window-close-symbolic", "Remove", "flat", lambda i=index: self._remove_queue(i))
        up.set_sensitive(index > 0)
        down.set_sensitive(index + 1 < len(self.queue))
        for widget in (index_label, title, duration_label, up, down, remove):
            box.append(widget)
        row.set_child(box)
        return row


    def _queue_row_matches(self, row) -> bool:
        return playlist_control.matches_query(
            row.get_tooltip_text() or "", self.queue_search.get_text()
        )


    def _on_queue_search(self, _entry) -> None:
        # Filtering never changes queue order or the current cast selection.
        self.queue_list.invalidate_filter()
        self._refresh_queue_visibility()


    def _on_queue_selected(self, _list, row) -> None:
        if row is None and self.queue_search.get_text().strip():
            return  # A hidden row must not change playback selection.
        selected_path = row.get_tooltip_text() if row is not None else None
        self.selected_index = (
            self.queue.index(selected_path) if selected_path in self.queue else None
        )
        if (self.selected_index is not None
                and 0 <= self.selected_index < len(self.queue)
                and self.session is None and not self.external):
            path = self.queue[self.selected_index]
            if path != self._preview_path:
                # Delay to avoid mutating a Gtk.ListBox during its selection signal.
                GLib.idle_add(lambda: (self.set_selection(path), False)[1]
                              if path != self._preview_path else False)


    def _on_queue_activated(self, _list, row) -> None:
        path = row.get_tooltip_text() if row is not None else None
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
        self._preview_pending = None
        self._unload_local_video()
        self._preview_path = None
        self._preview_position = 0.0
        self.preview_picture.set_visible(False)
        self.media = None
        self._update_audio_choices(None)
        self.embedded_dropdown.set_visible(False)
        self.seekbar.set_state(0.0, 0.0, 0.0)
        self.elapsed_label.set_text("00:00")
        self.remaining_label.set_text("--:--")
        self.np_title.set_text("Ready to cast")
        self.np_meta.set_text("Open a film to inspect and cast it")


    @staticmethod
    def _playlist_filters():
        store = Gio.ListStore.new(Gtk.FileFilter)
        playlists = Gtk.FileFilter()
        playlists.set_name("Playlists")
        for pattern in ("*.m3u", "*.m3u8"):
            playlists.add_pattern(pattern)
        store.append(playlists)
        return store, playlists


    def _load_playlist(self) -> None:
        # Chooser picks any named playlist; the parse runs off the GTK thread.
        dialog = Gtk.FileDialog(title="Load a playlist")
        store, playlists = self._playlist_filters()
        dialog.set_filters(store)
        dialog.set_default_filter(playlists)
        dialog.open(self, None, self._playlist_open_chosen)


    def _playlist_open_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # Cancelled: the queue must stay unchanged.
        path = gfile.get_path()
        if not path:
            return
        playlist = pathlib.Path(path)
        items_before = list(self.queue)

        def work():
            return playlist_control.load_playlist(playlist)

        def done(result):
            loaded, skipped = result
            additions = [item for item in loaded if item not in self.queue]
            if additions:
                self._enqueue(additions)
            self.toast(
                f"Playlist: {len(additions)} added"
                + (f", {skipped} missing or invalid" if skipped else "")
            )

        def failed(message):
            self.queue[:] = items_before
            self.toast(message, error=True)

        Async.run(work, done=done, failed=failed)


    def _save_playlist(self) -> None:
        if not self.queue:
            self.toast("Queue is empty", error=True)
            return
        dialog = Gtk.FileDialog(title="Save the queue as a playlist")
        dialog.set_initial_name("smoothcast_playlist.m3u")
        store, playlists = self._playlist_filters()
        dialog.set_filters(store)
        dialog.set_default_filter(playlists)
        dialog.save(self, None, self._playlist_save_chosen)


    def _playlist_save_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # Cancelled: nothing written.
        path = gfile.get_path()
        if not path:
            return
        destination = pathlib.Path(path)
        items = list(self.queue)

        def work():
            playlist_control.save_playlist(destination, items)
            return destination.name

        Async.run(
            work,
            done=lambda name: self.toast(f"Playlist saved: {name} ({len(items)} videos)"),
            failed=lambda message: self.toast(message, error=True),
        )


    def scan_devices(self) -> None:
        if self.scan_busy:
            # Queue one refresh, rather than publishing the older in-flight
            # result or launching unbounded simultaneous SSDP scans.
            self._scan_again = True
            return
        self._scan_again = False
        self.scan_busy = True
        self.device_detail.set_text("Scanning Cast and DLNA receivers…")

        def work():
            errors = []
            try:
                cast_devices = castctl.scan()
            except Exception as exc:
                cast_devices = []
                errors.append(f"Cast discovery: {exc}")
            try:
                dlna_devices = dlna.discover()
            except Exception as exc:
                dlna_devices = []
                errors.append(f"DLNA discovery: {exc}")
            if errors and not cast_devices and not dlna_devices:
                raise RuntimeError("; ".join(errors))
            return cast_devices, dlna_devices

        def completed(devices):
            if self._closing:
                self.scan_busy = False
                return
            if self._scan_again:
                self.scan_busy = False
                self.scan_devices()
                return
            self._scan_done(devices)

        def failed(message):
            if self._closing:
                self.scan_busy = False
                return
            if self._scan_again:
                self.scan_busy = False
                self.scan_devices()
                return
            self._scan_failed(message)

        Async.run(work, done=completed, failed=failed, domain="discovery")


    def _initial_scan(self) -> bool:
        self.scan_devices()
        return False


    def _scan_done(self, devices) -> None:
        self.scan_busy = False
        if isinstance(devices, tuple):
            cast_devices, discovered_dlna = devices
            self.dlna_devices = discovered_dlna
        else:
            cast_devices = devices
        self.devices = cast_devices
        self._dlna_by_key = {renderer.key: renderer for renderer in self.dlna_devices}
        # A receiver's friendly name may change without changing the physical
        # device. Only follow a stored UUID on an idle window, and only if
        # both UUID and resulting display name identify exactly one device.
        # Never retarget a live cast or a pending receiver command.
        saved_uuid = self.cfg.get("device_uuid", "")
        unlocked = not (self.session is not None or self.busy
                        or self._cast_starting or self.external)
        if unlocked and saved_uuid:
            matched = castctl.uniquely_named_device(saved_uuid, cast_devices)
            if matched is not None and matched.name != self.cfg["device"]:
                # A scheduled volume write and cached status still belong to
                # the old selection; do not carry either into a renamed target.
                if self._volume_job is not None:
                    GLib.source_remove(self._volume_job)
                    self._volume_job = None
                self._volume_target = None
                self.cfg["device"] = matched.name
                save_config(self.cfg)
                self.toast(f"Reconnected renamed Cast receiver: {matched.name}")
                self._poll_device()
        names = cast_targets.ordered_names(
            [d.name for d in cast_devices] + list(self._dlna_by_key),
            self.cfg.get("cast_targets", []),
            self.cfg.get("device_favourites", []),
            self.cfg.get("device_last_used"),
        )
        if self.cfg["device"] not in names:
            names.insert(0, self.cfg["device"])
        selected = names.index(self.cfg["device"])
        self._syncing = True
        self.device_dropdown.set_model(Gtk.StringList.new(names))
        self.device_dropdown.set_selected(selected)
        self._syncing = False
        selected = next((d for d in cast_devices if d.name == self.cfg["device"]), None)
        # Migrate older configurations when the selected display name itself
        # is unique. Do not adopt a duplicate name or overwrite a saved UUID.
        if not saved_uuid and selected is not None and selected.uuid:
            unique = castctl.uniquely_named_device(selected.uuid, cast_devices)
            if unique is selected:
                self.cfg["device_uuid"] = selected.uuid
                save_config(self.cfg)
        dlna_selected = self._dlna_renderer()
        if dlna_selected is not None:
            self.device_detail.set_text(
                f"DLNA/UPnP · {dlna_selected.model or 'MediaRenderer'} · {dlna_selected.host}"
            )
            self._set_device_badge("DLNA FOUND")
        elif selected is not None:
            self.device_detail.set_text(
                f"{selected.model or 'Google Cast receiver'} · {selected.manufacturer or 'Unknown maker'} · {selected.host}"
            )
            self._set_device_badge("FOUND ON LAN")
        elif self.cfg["device"] in self.cfg.get("cast_targets", []):
            self.device_detail.set_text(
                f"Manual Google Cast target {self.cfg['device']} · checking connectivity"
            )
            self._set_device_badge("MANUAL IP")
        else:
            self.device_detail.set_text(
                "Selected Cast receiver not found. Choose another receiver or add its IP."
                if cast_devices or self.dlna_devices else "No Cast or DLNA receivers discovered. Check Wi-Fi/VPN or firewall."
            )
            self._set_device_badge("NOT FOUND", "offline")


    def _scan_failed(self, message) -> None:
        self.scan_busy = False
        self.device_detail.set_text("Scan failed — is the network reachable?")
        self._set_device_badge("SCAN FAILED", "offline")
        self.toast(str(message), error=True)


    def _poll_device(self) -> bool:
        if self.poll_busy:
            return True
        self.poll_busy = True
        device = self._device()

        def completed(info):
            # Ignore an old TV's response if the target changed while the
            # background catt query was running; immediately query the new TV.
            if device != self._device():
                self.poll_busy = False
                self._poll_device()
                return
            self._poll_done(info)

        def failed(message):
            if device != self._device():
                self.poll_busy = False
                self._poll_device()
                return
            self._poll_failed(message)

        renderer = self._dlna_renderer(device)
        Async.run(
            (lambda: dlna.info(renderer)) if renderer else (lambda: castctl.info(device)),
            done=completed, failed=failed, domain="status",
        )
        return True


    def _poll_done(self, info) -> None:
        self.poll_busy = False
        previous = self.device_state
        self.device_info = info
        self.device_state = castctl.player_state(info)
        if info is None:
            self.device_state = "OFFLINE"
            self._set_device_badge("OFFLINE", "offline")
        elif self.device_state in {"PLAYING", "BUFFERING"}:
            self._set_device_badge("STREAMING", "online")
        else:
            self._set_device_badge("AVAILABLE", "online")
        self.tracker.set_state(self.device_state in {"PLAYING", "BUFFERING"})
        if self.session and info:
            # Chromecast reports the *new HLS playlist's* current_time from
            # zero after each seek. Convert it to source-file seconds, including
            # the original -ss offset and any non-1× playback rate. Direct play
            # already uses the source timeline and needs no conversion.
            current_time = info.get("current_time")
            duration = info.get("duration")
            if current_time is not None:
                try:
                    device_time = float(current_time)
                    state = self.session.state
                    if self.session.mode == "transcode" and state is not None:
                        absolute = playback_state.absolute_encoded_position(
                            state.offset, device_time, state.duration,
                            speed=state.speed,
                        )
                        if absolute is not None:
                            self.tracker.device_update(
                                absolute, state.duration, rate=state.speed,
                            )
                    else:
                        self.tracker.device_update(
                            device_time, float(duration) if duration else None,
                            rate=1.0,
                        )
                except (TypeError, ValueError, OverflowError):
                    pass
        volume = castctl.volume_percent(info)
        if volume is not None and time.time() - self._volume_user_ts > 3:
            self._syncing = True
            self.volume_scale.set_value(volume)
            self._syncing = False
        if info is not None:
            muted = castctl.volume_muted(info)
            self._syncing = True
            self.mute_button.set_active(muted)
            self._syncing = False
            self._apply_volume_icon()
        self._detect_external()
        if self.session is None and self._url_cast_url is not None:
            if playback_state.url_cast_matches(info, self._url_cast_url):
                self._url_cast_seen = True
            elif self._url_cast_seen:
                # A different active content replaced our URL cast; never stop
                # that replacement when the sleep timer expires.
                self._url_cast_url = None
                self._url_cast_seen = False
        if playback_state.playback_ended(
            previous, self.device_state,
            has_session=self.session is not None, busy=self.busy,
        ):
            self._maybe_finished()
        self._refresh_controls()
        self._update_header_subtitle()


    def _poll_failed(self, message) -> None:
        self.poll_busy = False
        self.device_info = None
        self.device_state = "OFFLINE"
        self._set_device_badge("OFFLINE", "offline")
        self._refresh_controls()
        self._console(f"Device status unavailable: {message}")


    def _add_cast_target(self) -> None:
        """Manually connect to a Google Cast receiver when mDNS is blocked."""
        # Return and Add IP reach this handler even when a widget is disabled
        # (for instance, a pending signal). Never retarget an owned TV.
        if (self.session is not None or self.busy
                or self._cast_starting or self.external):
            self.toast("Stop the current cast before changing TV", error=True)
            return
        try:
            target = castctl.validate_manual_target(self.cast_ip_entry.get_text())
        except ValueError as exc:
            self.toast(str(exc), error=True)
            return
        targets = self.cfg.get("cast_targets")
        if not isinstance(targets, list):
            targets = []
        if target not in targets:
            targets.append(target)
        self.cfg["cast_targets"] = targets[-32:]
        self.cfg["device"] = target
        self.cfg["device_uuid"] = ""  # Manual IP does not claim a discovered identity.
        save_config(self.cfg)
        self.cast_ip_entry.set_text("")
        self._scan_done(self.devices)
        self.toast(f"Added Google Cast target {target}; checking receiver")
        self._poll_device()


    def _on_device_selected(self, dropdown, _param) -> None:
        if self._syncing:
            return
        index = dropdown.get_selected()
        model = dropdown.get_model()
        if index == Gtk.INVALID_LIST_POSITION or model is None:
            return
        name = model.get_string(index)
        if (name and name != self.cfg["device"]
                and (self.session is not None or self.busy
                     or self._cast_starting or self.external)):
            # Keep A selected even if a queued GTK signal tries to select B.
            # Commands already in flight must retain their receiver identity.
            self._syncing = True
            try:
                for current_index in range(model.get_n_items()):
                    if model.get_string(current_index) == self.cfg["device"]:
                        dropdown.set_selected(current_index)
                        break
            finally:
                self._syncing = False
            self.toast("Stop the current cast before changing TV", error=True)
            return
        if name and name != self.cfg["device"]:
            # Never allow a previously queued volume write for A to affect B.
            if self._volume_job is not None:
                GLib.source_remove(self._volume_job)
                self._volume_job = None
            self._volume_target = None
            self.cfg["device"] = name
            matches = [d for d in self.devices if d.name == name and d.uuid]
            self.cfg["device_uuid"] = (
                matches[0].uuid if name not in self._dlna_by_key
                and name not in self.cfg.get("cast_targets", [])
                and len(matches) == 1
                and castctl.uniquely_named_device(matches[0].uuid, self.devices)
                    is matches[0] else ""
            )
            save_config(self.cfg)
            self.title_widget.set_subtitle(name)
            self.toast(f"Now controlling {name}")
            self._set_device_badge("CONNECTING")
            self._poll_device()


    def _detect_external(self) -> None:
        info = self.device_info
        idle = self.device_state in {"OFFLINE", "IDLE", "UNKNOWN"}
        if idle:
            if self.external:
                self.external = False
            # The receiver is no longer playing anything we started, so a
            # remembered URL cast must not be shown as owned or stopped later.
            self._url_cast_url = None
            self._url_cast_seen = False
            if not self.session:
                self.now_playing = None
                self.tracker.clear()
            return
        state = self.session.state if self.session is not None else None
        if state is not None:
            if (state.mode == "transcode" and
                    playback_state.hls_session_matches(
                        info, state.stream_url, state.title,
                    )):
                self.external = False  # Exact saved HLS URL; encoder may be done.
                return
            if (state.mode == "direct" and
                    playback_state.direct_session_matches(info, state.title)):
                self.external = False
                return
            if state.mode not in {"transcode", "direct"} and self.session.active():
                self.external = False
                return
        # A matching port, title or playlist suffix is NOT ownership proof.
        # Without a matching saved stream the receiver is playing other media.
        self.external = True
        self.tracker.clear()


    def _device(self) -> str:
        return self.cfg["device"]


    def _dlna_renderer(self, device: str | None = None) -> dlna.Renderer | None:
        return self._dlna_by_key.get(device or self._device())


    def _device_host(self, device: str) -> str | None:
        renderer = self._dlna_renderer(device)
        if renderer is not None:
            return renderer.host
        if device in self.cfg.get("cast_targets", []):
            return device
        return next((d.host for d in self.devices if d.name == device and d.host), None)
