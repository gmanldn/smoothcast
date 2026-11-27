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
        """Show the selected caption at the hovered source time; never block GTK."""
        self._caption_hover_position = at
        if at is None:
            self.subs_detail.set_text(self._subs_status_text())
            return
        if self.cfg.get("subs") not in {"pick", "auto", "embedded"} or not self._preview_path:
            return
        source_film = self._preview_path
        token_generation = getattr(self, "_preview_generation", 0)
        mode = self.cfg.get("subs")
        media = self.media if self.media is not None and str(self.media.path) == source_film else None
        subtitles = self._resolve_subs(pathlib.Path(source_film)) if mode in {"pick", "auto"} else None
        track = None
        if subtitles is None and mode == "embedded" and media is not None:
            saved = self.cfg.get("subtitle_track_by_file") or {}
            requested = saved.get(source_film, -1) if isinstance(saved, dict) else -1
            track = streamer.preferred_embedded_subtitle(media, requested)
            if track is None or not track.is_text:
                return
        if subtitles is not None and subtitles.suffix.lower() not in {".srt", ".vtt", ".ass", ".ssa"}:
            return
        source = subtitles if subtitles is not None else pathlib.Path(source_film)
        try:
            stamp = source.stat()
        except OSError:
            return
        kind = "sidecar" if subtitles is not None else "embedded"
        key = (kind, str(source), stamp.st_size, stamp.st_mtime_ns,
               track.index if track is not None else -1,
               track.codec if track is not None else "")

        def source_valid() -> bool:
            if (self.session is not None or self.external or self._preview_path != source_film
                    or self.cfg.get("subs") != mode
                    or getattr(self, "_preview_generation", 0) != token_generation):
                return False
            try:
                current = source.stat()
            except OSError:
                return False
            if (current.st_size, current.st_mtime_ns) != (stamp.st_size, stamp.st_mtime_ns):
                return False
            if track is not None:
                current_media = self.media
                choices = self.cfg.get("subtitle_track_by_file") or {}
                requested_now = choices.get(source_film, -1) if isinstance(choices, dict) else -1
                selected_now = streamer.preferred_embedded_subtitle(current_media, requested_now) \
                    if current_media is media else None
                return selected_now is not None and selected_now.index == track.index
            return True

        cached = getattr(self, "_caption_cue_cache", None)
        if cached is not None and cached[0] == key:
            caption = subtitle_encoding.cue_at(cached[1], at)
            base = self._subs_status_text()
            self.subs_detail.set_text(
                f"{base}\nAt {fmt_time(at)}: {caption}" if caption else base
            )
            return
        token = (key, token_generation)
        if getattr(self, "_caption_cue_pending", None) == token:
            return
        self._caption_cue_pending = token

        def work():
            try:
                if track is not None:
                    return subtitle_encoding.load_embedded_timed_cues(source, track.index)
                return subtitle_encoding.load_timed_cues(source)
            except subtitle_encoding.SubtitleEncodingError:
                # An unsupported/unreadable sidecar simply has no hover preview.
                # Cache "no cues" so hovering cannot retry and log it per move.
                return subtitle_encoding.TimedCues((), (), ())

        def done(cues):
            if getattr(self, "_caption_cue_pending", None) == token:
                self._caption_cue_pending = None
            if not source_valid():
                return
            self._caption_cue_cache = (key, cues)
            if self._caption_hover_position is not None:
                self._timed_subtitle_preview(self._caption_hover_position)

        def failed(message):
            if getattr(self, "_caption_cue_pending", None) == token:
                self._caption_cue_pending = None
            if source_valid():
                self._caption_cue_cache = (key, subtitle_encoding.TimedCues((), (), ()))
            if not getattr(self, "_closing", False):
                self._console(f"Subtitle cue preview unavailable: {message}")

        Async.run(
            work, done=done, failed=failed, domain="media",
            valid=lambda: (
                self.session is None and not self.external and
                source_valid()
            ),
        )
