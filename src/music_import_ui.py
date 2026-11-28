"""GTK controls for explicit audio/folder queue imports and drag/drop."""
from __future__ import annotations

import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

import music_import
import streamer

from cast_widgets import Async


class MusicImportController:
    """Composition replacement for MusicImportMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _build_music_actions(self) -> Gtk.MenuButton:
        w = self.w
        menu = Gtk.MenuButton(label="Add Music")
        popover = Gtk.Popover()
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        files = Gtk.Button(label="Choose audio files")
        folder = Gtk.Button(label="Add music folder")
        folders = Gtk.Button(label="Add multiple folders…")
        files.connect("clicked", lambda _b: (popover.popdown(), w.add_music()))
        folder.connect("clicked", lambda _b: (popover.popdown(), w.add_music_folder()))
        folders.connect("clicked", lambda _b: (popover.popdown(), w.add_music_folders()))
        actions.append(files)
        actions.append(folder)
        actions.append(folders)
        popover.set_child(actions)
        menu.set_popover(popover)
        return menu

    def _build_music_import_status(self) -> Gtk.Box:
        w = self.w
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_visible(False)
        w._music_scan_label = Gtk.Label(label="", xalign=0.0, hexpand=True)
        w._music_scan_label.add_css_class("caption")
        w._music_scan_bar = Gtk.ProgressBar()
        w._music_scan_bar.set_hexpand(True)
        w._music_scan_bar.set_pulse_step(0.08)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _b: w._cancel_music_import())
        row.append(w._music_scan_label)
        row.append(w._music_scan_bar)
        row.append(cancel)
        w._music_scan_status = row
        return row

    def _install_queue_drop_target(self, target: Gtk.Widget) -> None:
        w = self.w
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", w._drop_queue_media)
        target.add_controller(drop)

    def add_music(self) -> None:
        w = self.w
        dialog = Gtk.FileDialog(title="Add music to the queue")
        store = Gio.ListStore.new(Gtk.FileFilter)
        audio_filter = Gtk.FileFilter()
        audio_filter.set_name("Audio files")
        for suffix in sorted(streamer.AUDIO_EXTS):
            audio_filter.add_pattern(f"*{suffix}")
        store.append(audio_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        store.append(all_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(audio_filter)
        dialog.open_multiple(w, None, w._music_files_chosen)

    def add_music_folder(self) -> None:
        w = self.w
        dialog = Gtk.FileDialog(title="Add a music folder")
        dialog.select_folder(w, None, w._music_folder_chosen)

    def add_music_folders(self) -> None:
        w = self.w
        dialog = Gtk.FileDialog(title="Add music folders")
        dialog.select_multiple_folders(w, None, w._music_folders_chosen)

    def _music_files_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        w._start_music_import([
            path for index in range(files.get_n_items())
            if (path := files.get_item(index).get_path())
        ], audio_only=True, natural_sort=False)

    def _music_folder_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = folder.get_path()
        if path:
            w._start_music_import([path], audio_only=True)

    def _music_folders_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            files = dialog.select_multiple_folders_finish(result)
        except GLib.Error:
            return
        paths = [
            path for index in range(files.get_n_items())
            if (path := files.get_item(index).get_path())
        ]
        w._start_music_import(paths, audio_only=True, preview_order=len(paths) > 1)

    def _drop_queue_media(self, _target, file_list, _x, _y) -> bool:
        w = self.w
        sources = [file.get_path() for file in file_list.get_files() if file.get_path()]
        if not sources:
            w.toast("Drop local media files or folders onto the queue", error=True)
            return False
        w._start_music_import(sources, audio_only=False)
        return True

    def _start_music_import(
        w, sources: list[str], *, audio_only: bool, natural_sort: bool = True,
        preview_order: bool = False,
    ) -> None:
        if not sources:
            return
        w._cancel_music_import()
        w._music_scan_generation = getattr(w, "_music_scan_generation", 0) + 1
        generation = w._music_scan_generation
        cancel = threading.Event()
        w._music_scan_cancel = cancel
        w._music_scan_status.set_visible(True)
        w._music_scan_label.set_text("Preparing music import…")
        w._music_scan_bar.set_fraction(0.0)
        extensions = streamer.AUDIO_EXTS if audio_only else streamer.MEDIA_EXTS

        def progress(count: int) -> None:
            GLib.idle_add(w._show_music_import_progress, generation, count)

        def work():
            result = music_import.discover(
                sources, extensions=extensions, cancel=cancel, progress=progress,
                natural_sort=natural_sort,
            )
            metadata = {}
            for index, path in enumerate(result.paths, 1):
                if cancel.is_set():
                    break
                try:
                    metadata[path] = streamer.ffprobe(
                        Path(path), cancel=cancel,
                    )
                except Exception:  # noqa: BLE001 - a failed import is skipped
                    pass
                if index == 1 or index % 16 == 0 or index == len(result.paths):
                    GLib.idle_add(
                        w._show_music_tag_progress, generation, index, len(result.paths),
                    )
            skipped = 0
            for path in result.paths:
                if path not in metadata:
                    skipped += 1
            result = music_import.Discovery(
                paths=tuple(path for path in result.paths if path in metadata),
                visited=result.visited,
                skipped=result.skipped + skipped,
                truncated=result.truncated,
                cancelled=result.cancelled or cancel.is_set(),
            )
            return result, metadata, preview_order

        Async.run(
            work,
            done=lambda result: w._music_import_done(generation, *result),
            failed=lambda message: w._music_import_failed(generation, message),
            domain="media",
            valid=lambda: not w._closing and generation == w._music_scan_generation,
        )

    def _show_music_import_progress(self, generation: int, count: int) -> bool:
        w = self.w
        if generation == getattr(w, "_music_scan_generation", -1) and not w._closing:
            w._music_scan_label.set_text(f"Scanning folders… {count:,} entries")
            w._music_scan_bar.pulse()
        return False

    def _show_music_tag_progress(self, generation: int, count: int, total: int) -> bool:
        w = self.w
        if generation == getattr(w, "_music_scan_generation", -1) and not w._closing:
            w._music_scan_label.set_text(f"Reading track details… {count:,} of {total:,}")
            w._music_scan_bar.set_fraction(count / max(total, 1))
        return False

    def _finish_music_import(self, generation: int) -> bool:
        w = self.w
        if generation == getattr(w, "_music_scan_generation", -1):
            w._music_scan_cancel = None
            w._music_scan_status.set_visible(False)
        return generation == getattr(w, "_music_scan_generation", -1)

    def _music_import_done(
        w, generation: int, result: music_import.Discovery,
        metadata: dict[str, streamer.MediaInfo], preview_order: bool,
    ) -> None:
        if not w._finish_music_import(generation):
            return
        paths = music_import.order_tracks(list(result.paths), metadata)
        if result.paths and preview_order and not result.cancelled:
            w._show_music_import_preview(paths, result, metadata)
        else:
            w._accept_music_import(paths, result, metadata)

    def _show_music_import_preview(self, paths, result, metadata) -> None:
        w = self.w
        preview = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        for index, path in enumerate(paths[:200], 1):
            media = metadata.get(path)
            title = (f"{media.artist} — " if media and media.artist else "")
            title += (media.title if media and media.title else Path(path).name)
            if media and media.album:
                title += f" · {media.album}"
            label = Gtk.Label(label=f"{index}. {title}", xalign=0.0, wrap=True)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            preview.append(label)
        if len(paths) > 200:
            preview.append(Gtk.Label(label=f"… and {len(paths) - 200:,} more tracks", xalign=0.0))
        scroller = Gtk.ScrolledWindow(min_content_height=280, max_content_height=440)
        scroller.set_child(preview)
        summary = f"Proposed order for {len(paths):,} tracks. Review before adding them to Up Next."
        dialog = Adw.AlertDialog.new("Review music order", summary)
        dialog.set_extra_child(scroller)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", f"Add {len(paths):,} tracks")
        dialog.set_default_response("add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect(
            "response",
            lambda _dialog, response: w._accept_music_import(paths, result, metadata)
            if response == "add" else None,
        )
        dialog.present(w)

    def _accept_music_import(self, paths, result, metadata) -> None:
        w = self.w
        for path, media in metadata.items():
            try:
                info = Path(path).stat()
            except OSError:
                continue
            w._media_cache[path] = ((info.st_size, info.st_mtime_ns), media)
            w.queue_durations[path] = media.duration
        if paths:
            w._enqueue(list(paths))
        if result.cancelled:
            w.toast(f"Import cancelled after {result.visited:,} entries")
        elif result.truncated:
            w.toast(f"Import capped at {len(result.paths):,} items; choose a smaller folder")
        elif result.skipped:
            w.toast(f"Imported {len(result.paths):,}; skipped {result.skipped:,} unsupported or unreadable items")
        elif not result.paths:
            w.toast("No supported media files found", error=True)

    def _music_import_failed(self, generation: int, message: str) -> None:
        w = self.w
        if w._finish_music_import(generation):
            w.toast(f"Music import failed: {message}", error=True)

    def _cancel_music_import(self) -> None:
        w = self.w
        cancel = getattr(w, "_music_scan_cancel", None)
        if cancel is not None:
            cancel.set()
            if hasattr(w, "_music_scan_label"):
                w._music_scan_label.set_text("Stopping folder scan…")

    @classmethod
    def install(cls, window) -> "MusicImportController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in MUSIC_IMPORT_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


MUSIC_IMPORT_CONTROLLER_METHODS = ('_build_music_actions', '_build_music_import_status', '_install_queue_drop_target', 'add_music', 'add_music_folder', 'add_music_folders', '_music_files_chosen', '_music_folder_chosen', '_music_folders_chosen', '_drop_queue_media', '_start_music_import', '_show_music_import_progress', '_show_music_tag_progress', '_finish_music_import', '_music_import_done', '_show_music_import_preview', '_accept_music_import', '_music_import_failed', '_cancel_music_import')
