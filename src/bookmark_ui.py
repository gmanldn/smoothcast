"""Bookmark and watch-history menu and playback actions for the main window."""
from __future__ import annotations

import pathlib
import time

from gi.repository import Adw, Gio, GLib, Gtk

import bookmarks
import fingerprint
import watch_history
from cast_widgets import Async, fmt_time, save_config


class BookmarkUiMixin:
    def _build_bookmarks_menu(self) -> Gio.Menu:
        markers = Gio.Menu()
        markers.append("Add bookmark at current position…", "app.bookmark-add")
        for index, item in enumerate(bookmarks.clean(self.cfg.get("bookmarks"))):
            markers.append(
                f"{item['name']} — {item['media']} ({fmt_time(item['position'])})",
                f"app.bookmark-{index}",
            )
        if self.cfg.get("bookmarks"):
            markers.append("Clear bookmarks", "app.clear-bookmarks")
        return markers

    def _chapter_media(self):
        if self.external:
            return None
        if self.session is not None:
            state = getattr(self.session, "state", None)
            active = getattr(state, "file", None)
        else:
            active = self._preview_path
        media = getattr(self, "media", None)
        return media if media is not None and active and str(media.path) == str(active) else None

    def _build_chapters_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        media = self._chapter_media()
        if media is not None:
            for index, chapter in enumerate(getattr(media, "chapters", ())):
                label = f"{chapter.title} ({fmt_time(chapter.start)}–{fmt_time(chapter.end)})"
                item = Gio.MenuItem.new(label, None)
                item.set_action_and_target_value("app.chapter-jump", GLib.Variant("i", index))
                menu.append_item(item)
        return menu

    def _jump_to_chapter(self, index: int) -> None:
        media = self._chapter_media()
        chapters = getattr(media, "chapters", ()) if media is not None else ()
        if type(index) is not int or index < 0 or index >= len(chapters):
            self.toast("Chapter is unavailable for the current film", error=True)
            return
        self.seek_to(chapters[index].start, feedback_label=f"Chapter: {chapters[index].title}")

    def _bookmark_current(self) -> tuple[str | None, float | None]:
        previewing = self.session is None and self._preview_path is not None
        path = self._preview_path if previewing else self.now_playing
        position = self._preview_position if previewing else self.tracker.value()
        return path, position

    def _add_bookmark(self) -> None:
        path, position = self._bookmark_current()
        if not path or position is None:
            self.toast("Open or play a local video before saving a bookmark", error=True)
            return
        media = pathlib.Path(path).name
        position = max(0.0, float(position))
        self.toast("Identifying media for the bookmark…")
        Async.run(
            lambda: bookmarks.fingerprint(path),
            done=lambda digest: self._prompt_bookmark_name(path, media, position, digest),
            failed=lambda _message: self.toast(
                "Could not read this media file. Check that it is still available.", error=True,
            ),
        )

    def _prompt_bookmark_name(
        self, path: str, media: str, position: float, digest: str,
    ) -> None:
        entry = Gtk.Entry()
        entry.set_text(f"Bookmark {len(bookmarks.clean(self.cfg.get('bookmarks'))) + 1}")
        entry.set_max_length(bookmarks.MAX_LABEL)
        entry.set_activates_default(True)
        entry.update_property([Gtk.AccessibleProperty.LABEL], ["Bookmark name"])
        dialog = Adw.AlertDialog.new("Save bookmark", f"{media} at {fmt_time(position)}")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_default_response("save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def response(_dialog, result):
            if result != "save":
                return
            active_path, _ = self._bookmark_current()
            if active_path != path:
                self.toast("Playback changed; save the bookmark again", error=True)
                return
            try:
                self.cfg["bookmarks"] = bookmarks.add(
                    self.cfg.get("bookmarks"), digest, entry.get_text(), media,
                    position, time.time(),
                )
            except ValueError:
                self.toast("Enter a bookmark name and use a valid playback position.", error=True)
                return
            save_config(self.cfg)
            self.menu_button.set_menu_model(self._build_menu())
            self.toast(f"Saved bookmark: {entry.get_text().strip()}")

        dialog.connect("response", response)
        dialog.present(self)

    def _open_bookmark(self, index: int) -> None:
        item = bookmarks.at(self.cfg.get("bookmarks"), index)
        if item is None:
            return
        path, _ = self._bookmark_current()
        if not path:
            self.toast(f"Open {item['media']} before returning to this bookmark", error=True)
            return
        self.toast("Checking bookmark media…")

        def verified(digest: str) -> None:
            active_path, _ = self._bookmark_current()
            if active_path != path:
                self.toast("Playback changed; choose the bookmark again", error=True)
            elif digest != item["fingerprint"]:
                self.toast(f"This bookmark belongs to {item['media']}; open that file first", error=True)
            else:
                self.seek_to(item["position"])

        Async.run(
            lambda: bookmarks.fingerprint(path), done=verified,
            failed=lambda message: self.toast(f"Could not verify bookmark: {message}", error=True),
        )

    def _clear_bookmarks(self) -> None:
        self.cfg["bookmarks"] = []
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())
        self.toast("Bookmarks cleared")

    def _record_watch(self, event: str) -> None:
        """Append a bounded watch-state entry for the current film."""
        previewing = self.session is None and self._preview_path is not None
        path = self._preview_path if previewing else self.now_playing
        if not path:
            return
        source = "preview" if previewing else "cast"
        position = self._preview_position if previewing else (self.tracker.value() or 0.0)
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if not duration and previewing:
            duration = self.queue_durations.get(path, 0.0)
        tracks = {
            "audio": (self.cfg.get("audio_track_by_file") or {}).get(path),
            "subtitle": (self.cfg.get("subtitle_track_by_file") or {}).get(path),
        }
        stamp = watch_history.fingerprint(path)
        content_key = fingerprint.KEYS.get(path)   # non-blocking; None until hashed
        history = watch_history.record(
            self.cfg.get("watch_history"), path, event, position, time.time(),
            source=source, duration=duration, fingerprint=stamp, tracks=tracks,
            content_key=content_key,
        )
        if event == "start" and position:
            history = watch_history.record(
                history, path, "resumed", position, time.time(), source=source,
                duration=duration, fingerprint=stamp, tracks=tracks, content_key=content_key,
            )
        self.cfg["watch_history"] = history
        save_config(self.cfg)


    def _clear_watch_history(self) -> None:
        self.cfg["watch_history"] = watch_history.clear()
        save_config(self.cfg)
        self.toast("Watch history cleared")

    def _clear_favourites(self) -> None:
        self.cfg["favourites"] = []
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())
        self.toast("Favourites cleared")
    def _open_favourite(self, index: int) -> None:
        favourites = self.cfg.get("favourites", [])
        if not 0 <= index < len(favourites):
            return
        path = pathlib.Path(favourites[index])
        if not path.is_file():
            self.toast("That file has moved or been deleted", error=True)
            return
        self.open_paths([str(path)])
