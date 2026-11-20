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

from cast_widgets import save_config


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
