#!/usr/bin/env python3
"""Subtitle file selection and preview handlers for the main window."""
from __future__ import annotations

import pathlib
import re

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib
import streamer
import subtitle_delay
import subtitle_encoding
import subtitle_style

from cast_widgets import Async, fmt_time, save_config


class SubtitleFileMixin:
    def _subs_file_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            self._sync_subtitle_selection()
            return
        if not self._select_subtitle_file(gfile):
            self._sync_subtitle_selection()
    def _sync_subtitle_selection(self) -> None:
        self._syncing = True
        try:
            self.subs_dropdown.set_selected(
                {"off": 0, "auto": 1, "pick": 2, "embedded": 3}.get(self.cfg["subs"], 1)
            )
        finally:
            self._syncing = False
    def _drop_subtitle(self, _target, file_list, _x, _y) -> bool:
        files = file_list.get_files()
        if len(files) != 1:
            self.toast("Drop one subtitle file at a time", error=True)
            return False
        if not self._select_subtitle_file(files[0]):
            return False
        subtitle = pathlib.Path(self.cfg["subs_path"])
        tag = re.search(r"\.([a-z]{2,3}(?:-[a-z]{2})?)$", subtitle.stem, re.IGNORECASE)
        language = tag[1] if tag else "unknown"
        burn = (
            self._dlna_renderer() is not None or self.cfg.get("burn_subs", False)
            or subtitle.suffix.lower() not in streamer.CAST_SUBTITLE_EXTS
            or subtitle_delay.get(self.cfg, self._preview_path) != 0
            or subtitle_style.from_config(self.cfg) != subtitle_style.DEFAULT
        )
        mode = "Burn-in required" if burn else "Receiver subtitle track"
        cue = subtitle_encoding.cue_preview(subtitle)
        summary = f"{subtitle.name} · Language: {language} · {mode}"
        self.subs_detail.set_text(f"{summary}\n{cue}" if cue else summary)
        return True
    def _select_subtitle_file(self, gfile) -> bool:
        path = gfile.get_path()
        subtitle = pathlib.Path(path) if path else None
        if subtitle is None or subtitle.suffix.lower() not in streamer.SUBTITLE_EXTS or not subtitle.is_file():
            self.toast("Choose an existing .srt, .vtt, .ttml, .ass or .ssa file", error=True)
            return False
        self.cfg["subs"] = "pick"
        self.cfg["subs_path"] = path
        save_config(self.cfg)
        self._sync_subtitle_selection()
        self.subs_detail.set_text(self._subs_status_text())
        self.toast(f"Subtitles: {subtitle.name}")
        return True


    def _timed_subtitle_preview(self, at: float | None) -> None:
        """Show the sidecar cue at the hovered source time; never block GTK."""
        self._caption_hover_position = at
        if at is None:
            self.subs_detail.set_text(self._subs_status_text())
            return
        if self.cfg.get("subs") not in {"pick", "auto"} or not self._preview_path:
            return
        source_film = self._preview_path
        subtitles = self._resolve_subs(pathlib.Path(source_film))
        if subtitles is None or subtitles.suffix.lower() not in {".srt", ".vtt", ".ass", ".ssa"}:
            return
        try:
            stamp = subtitles.stat()
        except OSError:
            return
        key = (str(subtitles), stamp.st_size, stamp.st_mtime_ns)
        cached = getattr(self, "_caption_cue_cache", None)
        if cached is not None and cached[0] == key:
            caption = subtitle_encoding.cue_at(cached[1], at)
            base = self._subs_status_text()
            self.subs_detail.set_text(
                f"{base}\nAt {fmt_time(at)}: {caption}" if caption else base
            )
            return
        token = (key, getattr(self, "_preview_generation", 0))
        if getattr(self, "_caption_cue_pending", None) == token:
            return
        self._caption_cue_pending = token

        def work():
            return subtitle_encoding.load_timed_cues(subtitles)

        def done(cues):
            if getattr(self, "_caption_cue_pending", None) == token:
                self._caption_cue_pending = None
            if (self.session is not None or self.external or
                    self._preview_path != source_film or
                    getattr(self, "_preview_generation", 0) != token[1]):
                return
            try:
                current = subtitles.stat()
            except OSError:
                return
            if (str(subtitles), current.st_size, current.st_mtime_ns) != key:
                return
            self._caption_cue_cache = (key, cues)
            if self._caption_hover_position is not None:
                self._timed_subtitle_preview(self._caption_hover_position)

        def failed(message):
            if getattr(self, "_caption_cue_pending", None) == token:
                self._caption_cue_pending = None
            if not getattr(self, "_closing", False):
                self._console(f"Subtitle cue preview unavailable: {message}")

        Async.run(
            work, done=done, failed=failed, domain="media",
            valid=lambda: (
                self.session is None and not self.external and
                self._preview_path == source_film and
                getattr(self, "_preview_generation", 0) == token[1]
            ),
        )
