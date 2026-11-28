#!/usr/bin/env python3
"""Load and save the shared queue as an .m3u playlist."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk
import pathlib

import playlist_control

from cast_widgets import Async


class PlaylistController:
    """Composition replacement for PlaylistMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

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
        w = self.w
        # Chooser picks any named playlist; the parse runs off the GTK thread.
        dialog = Gtk.FileDialog(title="Load a playlist")
        store, playlists = w._playlist_filters()
        dialog.set_filters(store)
        dialog.set_default_filter(playlists)
        dialog.open(w, None, w._playlist_open_chosen)

    def _playlist_open_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # Cancelled: the queue must stay unchanged.
        path = gfile.get_path()
        if not path:
            return
        playlist = pathlib.Path(path)
        items_before = list(w.queue)

        def work():
            return playlist_control.load_playlist(playlist)

        def done(result):
            loaded, skipped = result
            additions = [item for item in loaded if item not in w.queue]
            if additions:
                w._enqueue(additions)
            w.toast(
                f"Playlist: {len(additions)} added"
                + (f", {skipped} missing or invalid" if skipped else "")
            )

        def failed(message):
            w.queue[:] = items_before
            w.toast(message, error=True)

        Async.run(work, done=done, failed=failed)

    def _save_playlist(self) -> None:
        w = self.w
        if not w.queue:
            w.toast("Queue is empty", error=True)
            return
        dialog = Gtk.FileDialog(title="Save the queue as a playlist")
        dialog.set_initial_name("smoothcast_playlist.m3u")
        store, playlists = w._playlist_filters()
        dialog.set_filters(store)
        dialog.set_default_filter(playlists)
        dialog.save(w, None, w._playlist_save_chosen)

    def _playlist_save_chosen(self, dialog, result) -> None:
        w = self.w
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # Cancelled: nothing written.
        path = gfile.get_path()
        if not path:
            return
        destination = pathlib.Path(path)
        items = list(w.queue)

        def work():
            playlist_control.save_playlist(destination, items)
            return destination.name

        Async.run(
            work,
            done=lambda name: w.toast(f"Playlist saved: {name} ({len(items)} videos)"),
            failed=lambda message: w.toast(message, error=True),
        )

    @classmethod
    def install(cls, window) -> "PlaylistController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in PLAYLIST_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


PLAYLIST_CONTROLLER_METHODS = ('_playlist_filters', '_load_playlist', '_playlist_open_chosen', '_save_playlist', '_playlist_save_chosen')
