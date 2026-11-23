"""Preferences row that previews crop/deinterlace detection for the selected film (#54).

Nothing is applied: it runs the same detectors the transcoder would use, off the
GTK thread, and shows one plain-language line. A film change while it runs, or a
failure, always puts the row back in a usable state.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

import video_policy
from cast_widgets import Async

IDLE_TEXT = "See what the two options above would do to the selected film. Nothing is changed."


class PictureCheck:
    def __init__(self, owner) -> None:
        self.owner = owner
        self.row = Adw.ActionRow(title="Check this film", subtitle=IDLE_TEXT)
        self.button = Gtk.Button(label="Check")
        self.button.set_valign(Gtk.Align.CENTER)
        self.button.connect("clicked", lambda _button: self.run())
        self.row.add_suffix(self.button)
        self.row.set_activatable_widget(self.button)

    def run(self) -> None:
        media = self.owner.media
        if media is None:
            self.row.set_subtitle("Select a film first.")
            return
        path = media.path
        self.button.set_sensitive(False)
        self.row.set_subtitle("Checking…")

        def work() -> str:
            found = video_policy.preview(str(path), media.duration, media.width, media.height,
                                         video_stream=media.video_stream_index)
            return video_policy.describe(found, media.width, media.height)

        def finish(text: str) -> None:
            current = self.owner.media
            same_film = current is not None and current.path == path
            self.row.set_subtitle(text if same_film else IDLE_TEXT)
            self.button.set_sensitive(True)

        Async.run(work, done=finish, failed=lambda _m: finish("Could not check this film."),
                  domain="background")
