#!/usr/bin/env python3
"""Load and save the shared queue as an .m3u playlist."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk
import pathlib

import playlist_control

from cast_widgets import Async


class PlaylistMixin:
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
