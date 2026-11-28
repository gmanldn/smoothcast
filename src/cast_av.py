#!/usr/bin/env python3
"""Audio, volume, subtitles, local preview and level monitoring."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk
import pathlib

import sys

import threading

import time

import castctl
import settings
import slider_accessibility
import command_trace
import benchmark

import dlna

import streamer

import audio_monitor

import screenshot

import picture_adjustments

import subtitle_search
from video_settings import VideoSettings

from cast_widgets import save_config, Async, fmt_time


class AvController:
    """Composition replacement for AvMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def _on_volume_changed(self, scale) -> None:
        w = self.w
        value = int(scale.get_value())
        w.volume_label.set_text(f"{value}%")
        slider_accessibility.sync_percent(scale, Gtk, value)
        w._apply_volume_icon()
        if w._syncing:
            return
        w._volume_user_ts = time.monotonic()
        w._volume_target = w._device()
        if w._volume_job is not None:
            GLib.source_remove(w._volume_job)
        w._volume_job = GLib.timeout_add(300, w._commit_volume)


    def _apply_volume_icon(self) -> None:
        w = self.w
        if w.mute_button.get_active():
            name = "audio-volume-muted-symbolic"
        else:
            value = w.volume_scale.get_value()
            if value < 1:
                name = "audio-volume-muted-symbolic"
            elif value < 34:
                name = "audio-volume-low-symbolic"
            elif value < 67:
                name = "audio-volume-medium-symbolic"
            else:
                name = "audio-volume-high-symbolic"
        w.mute_button.set_icon_name(name)


    def _commit_volume(self) -> bool:
        w = self.w
        w._volume_job = None
        # Debouncing must not reinterpret a change intended for TV A
        # as a fresh command to TV B after switching the selected device.
        target, w._volume_target = w._volume_target, None
        if w.device_state == "OFFLINE" or target is None or target != w._device():
            w._reject_volume()
            return False
        value = int(w.volume_scale.get_value())
        device = target
        renderer = w._dlna_renderer(device)
        if not w._volume_control_available():
            w._reject_volume("This DLNA receiver does not provide volume control")
            return False

        def current() -> bool:
            return not w._closing and device == w._device()

        def confirmed(_result=None) -> None:
            if current() and int(w.volume_scale.get_value()) == value:
                w.toast(f"Volume {value}%")

        if renderer is not None:
            Async.run(lambda: dlna.volume(renderer, value),
                      done=confirmed,
                      failed=lambda msg: w._reject_volume(f"DLNA volume: {msg}"),
                      valid=current, domain="transport")
        else:
            def done(result):
                if not current():
                    return
                ok, message = result
                if not ok:
                    w._reject_volume(message or "Volume change rejected")
                else:
                    confirmed()

            Async.run(lambda: castctl.volume(device, value),
                      done=done,
                      failed=lambda msg: w._reject_volume(f"Volume: {msg}"),
                      valid=current, domain="transport")
        return False


    def _reject_volume(self, message: str | None = None) -> None:
        """Undo an optimistic volume display the receiver never applied."""
        w = self.w
        if message:
            w.toast(message, error=True)
        known = castctl.volume_percent(w.device_info)
        if known is not None:
            w._syncing = True
            try:
                w.volume_scale.set_value(known)
            finally:
                w._syncing = False
        # Let the next poll resync the control with the receiver again.
        w._volume_user_ts = 0.0
        w._poll_device()


    def _nudge_volume(self, delta: int) -> None:
        w = self.w
        if not w._volume_control_available():
            w.toast("This DLNA receiver does not provide volume control", error=True)
            return
        w.volume_scale.set_value(max(0, min(100, w.volume_scale.get_value() + delta)))


    def _on_mute(self, button) -> None:
        w = self.w
        if w._syncing:
            return
        muted = button.get_active()
        w._apply_volume_icon()
        if w.device_state == "OFFLINE":
            return
        if not w._volume_control_available():
            w._syncing = True
            button.set_active(castctl.volume_muted(w.device_info))
            w._syncing = False
            w._apply_volume_icon()
            w.toast("This DLNA receiver does not provide mute control", error=True)
            return
        device = w._device()
        renderer = w._dlna_renderer(device)
        if renderer is not None:
            Async.run(lambda: dlna.set_muted(renderer, muted),
                      failed=lambda msg: w.toast(f"DLNA mute: {msg}", error=True), domain="transport")
        else:
            Async.run(lambda: castctl.set_muted(device, muted), domain="transport",
                      failed=lambda msg: w.toast(f"Mute failed: {msg}", error=True))
        w.toast("Muted" if muted else "Sound on")


    @command_trace.traced("desktop", "mute")
    def toggle_mute(self) -> None:
        w = self.w
        w.mute_button.set_active(not w.mute_button.get_active())


    def _on_gain(self, spin) -> None:
        w = self.w
        if w._syncing:
            return
        value = int(round(float(spin.get_value())))
        value = max(0, min(24, value))
        if value != w.cfg.get("audio_gain"):
            w.cfg["audio_gain"] = float(value)
            save_config(w.cfg)


    def _on_audio(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing:
            return
        mapping = {0: "original", 1: "dialogue", 2: "night"}
        value = mapping.get(dropdown.get_selected(), "dialogue")
        if value != w.cfg["audio"]:
            w.cfg["audio"] = value
            save_config(w.cfg)
            w.toast(f"Sound: {streamer.AUDIO_LABELS[value]} (restart to apply)")
        w._refresh_direct_note()


    def _on_audio_track(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing or w.media is None:
            return
        selected = dropdown.get_selected()
        tracks = w.media.audio_streams
        if not (0 <= selected <= len(tracks)):
            return
        choice = tracks[selected - 1].index if selected else -1
        path = str(w.media.path)
        active = w.session is not None and w.session.state is not None and w.session.state.file == path
        if active and w.busy:
            w.toast("Hold on — finishing the last cast command")
            w._update_audio_choices(w.media)
            return
        saved = w.cfg.get("audio_track_by_file")
        if not isinstance(saved, dict):
            saved = {}
        if (saved.get(path, -1) == choice
                and (not active or w.session.state.audio_track_index == choice)):
            return
        saved[path] = choice
        w.cfg["audio_track_by_file"] = saved
        save_config(w.cfg)
        w._refresh_direct_note()
        if active:
            # A new audio track requires re-encoding. Preserve the source-film
            # clock and do not allow two cast/seek jobs to race.
            position = w.tracker.value() or 0.0
            w.busy = True
            w._refresh_controls()
            w.tracker.device_update(position, w.media.duration)
            w._restart_at(w.session, position, audio_track_override=choice)
            w.toast("Switching audio track at current film position…")
        else:
            w.toast("Audio track saved for the next cast")


    def _update_audio_choices(self, media: streamer.MediaInfo | None) -> None:
        """Refresh a per-file audio picker without triggering a cast command."""
        w = self.w
        picker = getattr(w, "audio_track_dropdown", None)
        if picker is None:
            return
        w._syncing = True
        try:
            tracks = media.audio_streams if media is not None else []
            picker.set_model(Gtk.StringList.new(
                ["Auto (file default)"] + [t.label for t in tracks]
            ))
            saved = w.cfg.get("audio_track_by_file") or {}
            requested = saved.get(str(media.path), -1) if media is not None and isinstance(saved, dict) else -1
            selected = next(
                (i + 1 for i, track in enumerate(tracks) if track.index == requested), 0
            )
            picker.set_selected(selected)
            picker.set_sensitive(bool(tracks))
        finally:
            w._syncing = False


    def _on_embedded_track(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing or w.media is None or w._preview_path is None:
            return
        text_tracks = [track for track in w.media.subtitle_tracks if track.is_supported]
        index = dropdown.get_selected()
        chosen = text_tracks[index - 1].index if 1 <= index <= len(text_tracks) else -1
        w.cfg.setdefault("subtitle_track_by_file", {})[w._preview_path] = chosen
        w.cfg["subs"] = "embedded"
        save_config(w.cfg)
        w._syncing = True
        w.subs_dropdown.set_selected(3)
        w._syncing = False
        w.subs_detail.set_text(w._subs_status_text())


    def _update_embedded_choices(self, media: streamer.MediaInfo) -> None:
        w = self.w
        text_tracks = [track for track in media.subtitle_tracks if track.is_supported]
        w._syncing = True
        try:
            labels = ["Preferred embedded track"] + [track.label for track in text_tracks]
            w.embedded_dropdown.set_model(Gtk.StringList.new(labels))
            saved = w.cfg.get("subtitle_track_by_file") or {}
            selected = saved.get(str(media.path), -1) if isinstance(saved, dict) else -1
            position = next((n + 1 for n, track in enumerate(text_tracks)
                             if track.index == selected), 0)
            w.embedded_dropdown.set_selected(position)
            w.embedded_dropdown.set_visible(bool(text_tracks))
        finally:
            w._syncing = False
        w.subs_detail.set_text(w._subs_status_text())


    def _on_subs_mode(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing:
            return
        mapping = {0: "off", 1: "auto", 2: "pick", 3: "embedded"}
        value = mapping.get(dropdown.get_selected(), "auto")
        if value == "pick":
            dialog = Gtk.FileDialog(title="Choose a subtitle file")
            sub_filter = Gtk.FileFilter()
            sub_filter.set_name("Subtitles")
            for pattern in ("*.srt", "*.vtt", "*.ttml", "*.ass", "*.ssa"):
                sub_filter.add_pattern(pattern)
            store = Gio.ListStore.new(Gtk.FileFilter)
            store.append(sub_filter)
            dialog.set_filters(store)
            dialog.open(w, None, w._subs_file_chosen)
            return
        w.cfg["subs"] = value
        save_config(w.cfg)
        w.toast("Subtitles: " + {"off": "off", "auto": "auto", "embedded": "embedded track"}[value])
        w.subs_detail.set_text(w._subs_status_text())






    def _resolve_subs(self, video: pathlib.Path, *, config: dict | None = None) -> pathlib.Path | None:
        w = self.w
        cfg = w.cfg if config is None else config
        mode = cfg["subs"]
        if mode == "off":
            return None
        if mode == "pick":
            path = pathlib.Path(cfg["subs_path"]).expanduser()
            return path if path.is_file() and path.suffix.lower() in streamer.SUBTITLE_EXTS else None
        if mode != "auto":
            return None
        found = streamer.find_subtitles(video)
        if found is None:
            found = subtitle_search.find_subtitle(
                video, cfg.get("subtitle_search_folders"),
                preferred=cfg.get("preferred_subtitle_languages") or (),
            )
        return found


    def _active_subs(self) -> str | None:
        w = self.w
        mode = w.cfg["subs"]
        if mode == "off" or w.now_playing is None:
            return None
        if mode == "pick":
            path = pathlib.Path(w.cfg["subs_path"]).expanduser()
            return str(path) if path.is_file() else None
        return w._cached_subs(w.now_playing) if mode == "auto" else None


    def _cached_subs(self, path: str) -> str | None:
        w = self.w
        cached_path, cached_result = w._subs_cache
        if cached_path == path:
            return cached_result
        found = w._resolve_subs(pathlib.Path(path))
        result = str(found) if found else None
        w._subs_cache = (path, result)
        return result


    def _subs_status_text(self) -> str:
        w = self.w
        mode = w.cfg["subs"]
        if mode == "off":
            return "Subtitles off"
        if mode == "pick":
            path = w.cfg["subs_path"]
            return f"Using {pathlib.Path(path).name}" if path else "No subtitle file picked yet"
        if mode == "embedded" and w.media is not None:
            saved = w.cfg.get("subtitle_track_by_file") or {}
            selected = saved.get(str(w.media.path), -1) if isinstance(saved, dict) else -1
            chosen = streamer.preferred_embedded_subtitle(w.media, selected)
            return f"Embedded: {chosen.label}" if chosen else "No supported embedded text track; choose a .srt file"
        if w.now_playing:
            found = w._cached_subs(w.now_playing)
            if found:
                return f"Found subtitle: {pathlib.Path(found).name}"
        if w.media is not None and w.media.subtitle_tracks:
            chosen = streamer.preferred_embedded_subtitle(w.media)
            if chosen is not None:
                return f"MKV embedded text available: {chosen.label}"
            return "Bitmap subtitles are not supported; load an .srt file"
        return "Matches an external subtitle file or selects a compatible MKV text track"


    def _on_quality(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing:
            return
        mapping = {0: "high", 1: "balanced", 2: "saver"}
        value = mapping.get(dropdown.get_selected(), "balanced")
        if value != w.cfg["quality"] or w.cfg.get("quality_auto", True):
            w.cfg["quality"] = value
            w.cfg["quality_auto"] = False  # Explicit choice wins over the CPU probe.
            save_config(w.cfg)
            w.toast(f"Quality: {streamer.QUALITY_LABELS[value]} (restart to apply)")


    def _on_rotation(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing:
            return
        mapping = {0: 0, 1: 90, 2: 180, 3: 270}
        value = mapping.get(dropdown.get_selected(), 0)
        if value != VideoSettings.from_config(w.cfg).rotation:
            w.cfg["rotation"] = value
            save_config(w.cfg)
            w.toast(f"Video rotation {value}° (restart to apply)")


    def _on_cc_toggled(self, button) -> None:
        w = self.w
        if w.busy or w._syncing:
            return
        on = button.get_active()
        if w._dlna_renderer() is not None:
            w._restore_cc_toggle(not on)
            w.toast("DLNA subtitles are burned into the prepared film; recast to change", error=True)
            return
        device = w._device()
        previous = w.cfg["subs"]

        def work():
            return castctl.subs_on(device) if on else castctl.subs_off(device)

        def done(result):
            ok, message = result
            if ok:
                # Persist the receiver's acknowledged state so the next status
                # refresh cannot re-derive the toggle from subtitle presence.
                w.cfg["subs"] = (
                    (previous if previous != "off" else "auto") if on else "off"
                )
                save_config(w.cfg)
            else:
                w._restore_cc_toggle(not on)
            w.toast("Captions on" if on and ok else ("Captions off" if ok else (message or "Caption toggle failed")))

        def failed(message):
            w._restore_cc_toggle(not on)
            w.toast(f"Captions failed: {message}", error=True)

        Async.run(work, done=done, failed=failed, domain="transport",
                  valid=lambda: not w._closing and w._device() == device)


    def _restore_cc_toggle(self, active: bool) -> None:
        """Put the CC toggle back without emitting a fresh receiver command."""
        w = self.w
        w._syncing = True
        try:
            w.cc_button.set_active(active)
        finally:
            w._syncing = False


    def _start_preview(self) -> bool:
        w = self.w
        w._preview_timer_id = 0
        if w._preview_busy or w._preview_pending is None:
            return False
        path, position, generation = w._preview_pending
        sparse = bool(getattr(w, "_preview_sparse", False))
        fast = bool(getattr(w, "_preview_fast", False)) and not sparse
        w._preview_sparse = False
        w._preview_fast = False
        w._preview_pending = None
        if path != w._preview_path or generation != w._preview_generation:
            return False
        w._preview_busy = True
        w._preview_inflight_sparse = sparse

        def finish(frame=None):
            w._preview_busy = False
            owned = (path == w._preview_path
                     and generation == w._preview_generation
                     and w.session is None and not w.external
                     and not getattr(w, "_local_video_path", None)
                     and not getattr(w, "_closing", False))
            latest = owned and w._preview_pending is None
            # Show a decoded frame whenever it is at least as close to the
            # playhead as the one on screen. Dropping every frame while a newer
            # request was pending froze the picture until the drag stopped and
            # then made it jump; going backwards to an older frame is what a
            # stale decode must never do.
            head = getattr(w, "_preview_head", position)
            shown = getattr(w, "_preview_shown", None)
            shown_position = shown[2] if shown and shown[:2] == (path, generation) else None
            closer = (shown_position is None
                      or abs(position - head) <= abs(shown_position - head))
            if latest and sparse:
                w._refresh_thumbnail_strip(position, visible=True)
            elif owned and not sparse and closer:
                if frame is not None:
                    try:
                        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(frame))
                        w.preview_picture.set_paintable(texture)
                        w.preview_picture.set_visible(True)
                        w._preview_shown = (path, generation, position)
                    except GLib.Error:
                        w.preview_picture.set_visible(False)
                        w._preview_shown = None
                elif shown_position is None:
                    w.preview_picture.set_visible(False)
            if w._preview_pending is not None and not w._preview_timer_id:
                delay = 120 if w._preview_sparse else 1
                w._preview_timer_id = GLib.timeout_add(delay, w._start_preview)

        media = w.media if w.media is not None and str(w.media.path) == path else None
        if media is not None and media.is_audio_only:
            if VideoSettings.from_config(w.cfg).show_cover_art:
                Async.run(
                    lambda: screenshot.cover_art(pathlib.Path(path)),
                    done=finish, failed=lambda _error: finish(), domain="media",
                )
            else:
                finish()
            return False
        video_index = media.video_stream_index if media is not None else 0
        aspect_mode = VideoSettings.from_config(w.cfg).aspect_override
        aspect_options = {"aspect_mode": aspect_mode} if aspect_mode != "original" else {}
        # Snapshot settings for asynchronous decodes; do not read a changing GTK config
        # from the worker after a user moves a colour control. Per-film presets win.
        picture_config = picture_adjustments.for_path(w.cfg, path)
        if sparse:
            cache = getattr(w, "_sparse_frame_cache", None)
            if cache is None:
                cache = screenshot.SparseFrameCache()
                w._sparse_frame_cache = cache
            key = cache.key(path, generation, video_index, position)
            cached = cache.get(key)
            if cached is not None:
                finish(cached)
                return False
            sample = cache.sample(position)
            def ready(frame):
                cache.put(key, frame)
                finish(frame)
            Async.run(
                lambda: screenshot.preview_frame(
                    pathlib.Path(path), sample, video_stream_index=video_index, picture_config=picture_config, **aspect_options,
                ),
                done=ready, failed=lambda _error: finish(), domain="media",
            )
            return False
        # An explicit seek or frame step must not be approximated by a hover bin.
        if fast:
            aspect_options = {**aspect_options, "fast": True}
        Async.run(
            lambda: screenshot.preview_frame(
                pathlib.Path(path), position, video_stream_index=video_index, picture_config=picture_config, **aspect_options,
            ),
            done=finish, failed=lambda _error: finish(), domain="media",
        )
        return False


    def _thumbnail_identity(self) -> tuple[str, int, int] | None:
        w = self.w
        media = w.media
        path = w._preview_path
        if (path is None or media is None or media.is_audio_only or str(media.path) != path
                or w.session is not None or w.external
                or getattr(w, "_url_cast_url", None) or getattr(w, "_closing", False)):
            return None
        return path, w._preview_generation, media.video_stream_index


    def _refresh_thumbnail_strip(self, position: float, *, visible: bool) -> None:
        """Show nearby cached hover frames without scheduling a decoder."""
        w = self.w
        strip = getattr(w, "thumbnail_strip", None)
        if strip is None:
            return
        source = w._thumbnail_identity() if visible else None
        cache = getattr(w, "_sparse_frame_cache", None)
        entries = tuple(cache.nearby(*source, position)) if source and cache is not None else ()
        render_key = source, entries
        if render_key == getattr(w, "_thumbnail_render_key", None):
            return

        w._thumbnail_render_key = render_key
        frames = []
        for moment, image in entries:
            try:
                frames.append((moment, Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))))
            except GLib.Error:
                continue  # Skip an invalid JPEG without blocking the other cached frames.

        w._thumbnail_positions = [moment for moment, _texture in frames]
        for index, (button, picture, label) in enumerate(zip(
                w.thumbnail_buttons, w.thumbnail_pictures, w.thumbnail_times)):
            if index < len(frames):
                moment, texture = frames[index]
                picture.set_paintable(texture)
                time_label = fmt_time(moment)
                label.set_text(time_label)
                action = f"Seek to {time_label}"
                button.set_tooltip_text(action)
                button.update_property([Gtk.AccessibleProperty.LABEL], [action])
                button.set_visible(True)
            else:
                picture.set_paintable(None)
                label.set_text("")
                button.set_visible(False)
        strip.set_visible(bool(frames))


    def _on_thumbnail_clicked(self, _button, index: int) -> None:
        """Seek only while the original local preview still owns the strip."""
        w = self.w
        positions = getattr(w, "_thumbnail_positions", [])
        if not 0 <= index < len(positions):
            return
        if w._thumbnail_render_key[0] != w._thumbnail_identity():
            w._refresh_thumbnail_strip(0.0, visible=False)
            return
        w.seek_to(positions[index])


    def _show_nearest_preview(self, position: float) -> None:
        """Put the closest already-decoded frame on screen at once.

        Called on the GTK thread for every scrub step: a cache lookup and one
        small JPEG upload, never a decoder. The exact frame replaces it later.
        """
        w = self.w
        source = w._thumbnail_identity()
        cache = getattr(w, "_sparse_frame_cache", None)
        if source is None or cache is None or getattr(w, "_local_video_path", None):
            return
        found = cache.nearest(*source, position)
        if found is None:
            return
        moment, image = found
        shown = getattr(w, "_preview_shown", None)
        if shown is not None and shown[:2] == source[:2]:
            # Keep whatever is already closer to the playhead (e.g. an exact frame).
            if abs(shown[2] - position) <= abs(moment - position):
                return
        try:
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
        except GLib.Error:
            return
        w.preview_picture.set_paintable(texture)
        w.preview_picture.set_visible(True)
        w._preview_shown = (source[0], source[1], moment)


    def _queue_preview(self, position: float, *, sparse: bool = False, fast: bool = False) -> None:
        """Debounce frame decoding, with at most one FFmpeg worker at a time."""
        w = self.w
        if (w._preview_path is None or w.session is not None or w.external
                or w._local_stream() is not None):
            return
        # Hover must neither replace a committed seek nor discard its result.
        if sparse and ((w._preview_pending is not None and not w._preview_sparse)
                       or (w._preview_busy and not getattr(w, "_preview_inflight_sparse", False))):
            return
        w._preview_pending = (w._preview_path, max(0.0, position),
                                 w._preview_generation)
        if not sparse:
            w._preview_head = max(0.0, position)  # where the playhead is now
        w._preview_fast = fast and not sparse
        w._preview_sparse = sparse
        if not sparse and w._preview_timer_id:
            GLib.source_remove(w._preview_timer_id)
            w._preview_timer_id = 0
        if not w._preview_timer_id and not w._preview_busy:
            # Exact seeks run on the next main-loop turn, not the hover debounce.
            delay = 180 if sparse else 1
            w._preview_timer_id = GLib.timeout_add(delay, w._start_preview)


    def _toggle_local_preview(self) -> None:
        """Play/pause locally in the embedded video panel, never on the TV."""
        w = self.w
        if w.session is not None or w.external:
            return
        path = w._preview_path
        if path is None:
            w.open_video()
            return
        stream = w._local_stream()
        if stream is not None and stream.get_playing():
            w._preview_position = max(0.0, stream.get_timestamp() / 1_000_000)
            stream.pause()
            w._stop_local_meter()
            w._refresh_controls()
            return
        if stream is not None and stream.get_error() is not None:
            w.toast("Preview could not decode this file. Try another format or codec.", error=True)
            w._unload_local_video()
            return
        if w._local_video_path != path:
            w._unload_local_video()
            w._local_start_pending = w._preview_position
            w._local_video_path = path
            w.local_video.set_file(Gio.File.new_for_path(path))
            stream = w._local_stream()
            if stream is None:
                w._unload_local_video()
                w.toast("Video backend unavailable; install GTK GStreamer media support", error=True)
                return
            stream.connect("notify::prepared", w._on_local_prepared, path)
            stream.connect("notify::error", w._on_local_error, path)
            if stream.is_prepared():
                w._on_local_prepared(stream, None, path)
        elif stream is not None and w._local_start_pending is None:
            stream.play()
            w._start_local_meter(w._preview_position)
        w.preview_picture.set_visible(False)
        w.local_video.set_visible(True)
        w._refresh_controls()


    def _local_stream(self):
        w = self.w
        return w.local_video.get_media_stream() if w._local_video_path else None


    def _preview_monitor_chain(self) -> tuple[list, str]:
        """Meter chain and hint for the audio of the locally previewed file."""
        w = self.w
        profile = str(w.cfg.get("audio", "dialogue"))
        audio = settings.AudioSettings.from_config(w.cfg)
        gain, mode = audio.gain, audio.loudness
        chain, hint = streamer.monitor_summary(profile, gain, mode)
        return chain, "Local preview · " + hint


    def _start_local_meter(self, position: float) -> None:
        """Feed the line meters from the file playing in the local preview."""
        w = self.w
        path = w._local_video_path or w._preview_path
        if path is None:
            return
        chain, hint = w._preview_monitor_chain()
        w._start_monitor(path, max(0.0, position), chain)
        w._set_levels_hint(hint)


    def _stop_local_meter(self) -> None:
        """Idle the meters when local playback stops, never a cast's meter."""
        w = self.w
        if w._local_video_path is None:
            return
        w._stop_monitor()
        w._set_levels_hint("")


    def _meter_position(self) -> float | None:
        """Position (seconds) of the audio the meters are showing."""
        w = self.w
        stream = w._local_stream()
        if stream is not None and w._local_video_path is not None:
            if not stream.get_playing():
                return None
            return max(0.0, stream.get_timestamp() / 1_000_000)
        return w.tracker.value()


    def _play_locally(self) -> None:
        w = self.w
        w._toggle_local_preview()


    def _selected_path(self) -> str | None:
        w = self.w
        if w.session is None and w._preview_path is not None:
            return w._preview_path
        if w.now_playing:
            return w.now_playing
        if w.selected_index is not None and 0 <= w.selected_index < len(w.queue):
            return w.queue[w.selected_index]
        return None


    def _current_media(self) -> streamer.MediaInfo | None:
        w = self.w
        if w.media is not None and w.now_playing is not None and str(w.media.path) == w.now_playing:
            return w.media
        return None


    def _on_local_prepared(self, stream, _param, path: str) -> None:
        w = self.w
        if path != w._local_video_path or not stream.is_prepared():
            return
        if w._local_start_pending is None:
            return
        start = float(w._local_start_pending)
        stream.seek(int(start * 1_000_000))
        w._local_start_pending = None
        stream.play()
        w._start_local_meter(start)
        w._record_watch("start")
        w._refresh_controls()


    def _on_local_error(self, stream, _param, path: str) -> None:
        w = self.w
        if path != w._local_video_path:
            return
        error = stream.get_error()
        if error is not None:
            w.toast("Preview could not decode this file. Try another format or codec.", error=True)
            w._unload_local_video()
            w.preview_picture.set_visible(False)
            w._queue_preview(w._preview_position)
            w._refresh_controls()


    def _unload_local_video(self) -> None:
        w = self.w
        w._cancel_queue_prewarm()
        w._stop_local_meter()
        w._record_watch("stop")
        stream = w._local_stream()
        if stream is not None:
            stream.pause()
        w._local_start_pending = None
        w._local_video_path = None
        if hasattr(w, "local_video"):
            w.local_video.set_file(None)
            w.local_video.set_visible(False)


    def _start_monitor(self, media_path, offset: float, chain) -> None:
        w = self.w
        w._stop_monitor()
        if media_path is None:
            return
        w._prewarm_queue_media()
        try:
            w._mon_path = pathlib.Path(media_path)
            w._mon_chain = list(chain)
            w.monitor = audio_monitor.AudioMonitor()
            track_index = -1
            if w.media is not None and w.media.path == w._mon_path:
                chosen = (w.session.state.audio_track_index
                          if w.session is not None and w.session.state is not None else -1)
                track = streamer.preferred_audio_track(w.media, chosen)
                track_index = track.index if track is not None else 0
            w.monitor.start(
                w._mon_path, w._mon_chain, offset=max(0.0, offset),
                audio_track_index=track_index,
            )
        except Exception:  # noqa: BLE001 - no meter means no meter; playback continues
            w.monitor = None
        w._sync_ui_timers()


    def _stop_monitor(self, reset: bool = True) -> None:
        w = self.w
        mon, w.monitor = w.monitor, None
        if mon is not None:
            # Stopping FFmpeg and joining its reader can take several seconds.
            # Never do that on GTK's main event loop during seek/pause/close.
            def dispose():
                try:
                    mon.stop()
                except Exception as exc:  # noqa: BLE001 - meter cleanup failure is reported to stderr
                    print(f"SmoothCast: meter cleanup failed: {exc}", file=sys.stderr)
            threading.Thread(
                target=dispose, name="smoothcast-meter-stop", daemon=False,
            ).start()
        if reset and w.meter is not None:
            w.meter.reset()
        w._sync_ui_timers()


    def _resume_monitor(self) -> None:
        w = self.w
        if w._mon_path is None or w.media is None:
            return
        if not (w.session and w.session.active()):
            return
        pos = w.tracker.value() or 0.0
        w._start_monitor(w._mon_path, pos, w._mon_chain)


    def _meter_tick(self) -> bool:
        w = self.w
        mon = w.monitor
        meter = w.meter
        if mon is None or meter is None:
            if meter is not None:
                meter.set_sample(None)
            return True
        position = w._meter_position()
        if position is None:
            meter.set_sample(None)
        else:
            meter.set_sample(mon.sample_at(position))
        return True


    def action_benchmark(self, *_args) -> None:
        """Measure encode speed and recommend a quality tier (SC-048 #57)."""
        w = self.w
        dialog = Adw.Dialog()
        dialog.set_title("Playback-quality benchmark")
        dialog.set_content_width(380)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        result = Gtk.Label(
            label="Press Run to measure this machine's 1080p encode speed.",
            wrap=True, xalign=0.0,
        )
        box.append(result)
        run = Gtk.Button(label="Run benchmark")
        run.add_css_class("suggested-action")

        def start(_button):
            result.set_text("Running a short 1080p encode test…")
            source_fps = w.media.fps if w.media and w.media.fps else 30.0

            def work():
                return benchmark.recommend(benchmark.run_probe(), source_fps)

            def done(rec):
                result.set_text(
                    f"Recommend {rec['tier']}\n{rec['reason']}\n"
                    f"Trade-off: {rec['tradeoff']}"
                )

            Async.run(
                work, done=done,
                failed=lambda message: result.set_text(f"Benchmark failed: {message}"),
            )

        run.connect("clicked", start)
        box.append(run)
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(w)

    @classmethod
    def install(cls, window) -> "AvController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in AV_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


AV_CONTROLLER_METHODS = ('_on_volume_changed', '_apply_volume_icon', '_commit_volume', '_reject_volume', '_nudge_volume', '_on_mute', 'toggle_mute', '_on_gain', '_on_audio', '_on_audio_track', '_update_audio_choices', '_on_embedded_track', '_update_embedded_choices', '_on_subs_mode', '_resolve_subs', '_active_subs', '_cached_subs', '_subs_status_text', '_on_quality', '_on_rotation', '_on_cc_toggled', '_restore_cc_toggle', '_start_preview', '_thumbnail_identity', '_refresh_thumbnail_strip', '_on_thumbnail_clicked', '_show_nearest_preview', '_queue_preview', '_toggle_local_preview', '_local_stream', '_preview_monitor_chain', '_start_local_meter', '_stop_local_meter', '_meter_position', '_play_locally', '_selected_path', '_current_media', '_on_local_prepared', '_on_local_error', '_unload_local_video', '_start_monitor', '_stop_monitor', '_resume_monitor', '_meter_tick', 'action_benchmark')
