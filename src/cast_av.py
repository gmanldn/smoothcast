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
import benchmark

import dlna

import streamer

import audio_monitor

import screenshot

from cast_widgets import save_config, Async


class AvMixin:
    def _on_volume_changed(self, scale) -> None:
        value = int(scale.get_value())
        self.volume_label.set_text(f"{value}%")
        self._apply_volume_icon()
        if self._syncing:
            return
        self._volume_user_ts = time.time()
        self._volume_target = self._device()
        if self._volume_job is not None:
            GLib.source_remove(self._volume_job)
        self._volume_job = GLib.timeout_add(300, self._commit_volume)


    def _apply_volume_icon(self) -> None:
        if self.mute_button.get_active():
            name = "audio-volume-muted-symbolic"
        else:
            value = self.volume_scale.get_value()
            if value < 1:
                name = "audio-volume-muted-symbolic"
            elif value < 34:
                name = "audio-volume-low-symbolic"
            elif value < 67:
                name = "audio-volume-medium-symbolic"
            else:
                name = "audio-volume-high-symbolic"
        self.mute_button.set_icon_name(name)


    def _commit_volume(self) -> bool:
        self._volume_job = None
        # Debouncing must not reinterpret a change intended for TV A
        # as a fresh command to TV B after switching the selected device.
        target, self._volume_target = self._volume_target, None
        if self.device_state == "OFFLINE" or target is None or target != self._device():
            self._reject_volume()
            return False
        value = int(self.volume_scale.get_value())
        device = target
        renderer = self._dlna_renderer(device)
        if not self._volume_control_available():
            self._reject_volume("This DLNA receiver does not provide volume control")
            return False
        if renderer is not None:
            Async.run(lambda: dlna.volume(renderer, value),
                      failed=lambda msg: self._reject_volume(f"DLNA volume: {msg}"), domain="transport")
        else:
            def done(result):
                ok, message = result
                if not ok:
                    self._reject_volume(message or "Volume change rejected")

            Async.run(lambda: castctl.volume(device, value),
                      done=done,
                      failed=lambda msg: self._reject_volume(f"Volume: {msg}"), domain="transport")
        return False


    def _reject_volume(self, message: str | None = None) -> None:
        """Undo an optimistic volume display the receiver never applied."""
        if message:
            self.toast(message, error=True)
        known = castctl.volume_percent(self.device_info)
        if known is not None:
            self._syncing = True
            try:
                self.volume_scale.set_value(known)
            finally:
                self._syncing = False
        # Let the next poll resync the control with the receiver again.
        self._volume_user_ts = 0.0
        self._poll_device()


    def _nudge_volume(self, delta: int) -> None:
        if not self._volume_control_available():
            self.toast("This DLNA receiver does not provide volume control", error=True)
            return
        self.volume_scale.set_value(max(0, min(100, self.volume_scale.get_value() + delta)))


    def _on_mute(self, button) -> None:
        if self._syncing:
            return
        muted = button.get_active()
        self._apply_volume_icon()
        if self.device_state == "OFFLINE":
            return
        if not self._volume_control_available():
            self._syncing = True
            button.set_active(castctl.volume_muted(self.device_info))
            self._syncing = False
            self._apply_volume_icon()
            self.toast("This DLNA receiver does not provide mute control", error=True)
            return
        device = self._device()
        renderer = self._dlna_renderer(device)
        if renderer is not None:
            Async.run(lambda: dlna.set_muted(renderer, muted),
                      failed=lambda msg: self.toast(f"DLNA mute: {msg}", error=True), domain="transport")
        else:
            Async.run(lambda: castctl.set_muted(device, muted), domain="transport",
                      failed=lambda msg: self.toast(f"Mute failed: {msg}", error=True))
        self.toast("Muted" if muted else "Sound on")


    def toggle_mute(self) -> None:
        self.mute_button.set_active(not self.mute_button.get_active())


    def _on_gain(self, spin) -> None:
        if self._syncing:
            return
        value = int(round(float(spin.get_value())))
        value = max(0, min(24, value))
        if value != self.cfg.get("audio_gain"):
            self.cfg["audio_gain"] = float(value)
            save_config(self.cfg)


    def _on_audio(self, dropdown, _param) -> None:
        if self._syncing:
            return
        mapping = {0: "original", 1: "dialogue", 2: "night"}
        value = mapping.get(dropdown.get_selected(), "dialogue")
        if value != self.cfg["audio"]:
            self.cfg["audio"] = value
            save_config(self.cfg)
            self.toast(f"Sound: {streamer.AUDIO_LABELS[value]} (restart to apply)")
        self._refresh_direct_note()


    def _on_audio_track(self, dropdown, _param) -> None:
        if self._syncing or self.media is None:
            return
        selected = dropdown.get_selected()
        tracks = self.media.audio_streams
        if not (0 <= selected <= len(tracks)):
            return
        choice = tracks[selected - 1].index if selected else -1
        path = str(self.media.path)
        active = self.session is not None and self.session.state is not None and self.session.state.file == path
        if active and self.busy:
            self.toast("Hold on — finishing the last cast command")
            self._update_audio_choices(self.media)
            return
        saved = self.cfg.get("audio_track_by_file")
        if not isinstance(saved, dict):
            saved = {}
        if (saved.get(path, -1) == choice
                and (not active or self.session.state.audio_track_index == choice)):
            return
        saved[path] = choice
        self.cfg["audio_track_by_file"] = saved
        save_config(self.cfg)
        self._refresh_direct_note()
        if active:
            # A new audio track requires re-encoding. Preserve the source-film
            # clock and do not allow two cast/seek jobs to race.
            position = self.tracker.value() or 0.0
            self.busy = True
            self._refresh_controls()
            self.tracker.device_update(position, self.media.duration)
            self._restart_at(self.session, position, audio_track_override=choice)
            self.toast("Switching audio track at current film position…")
        else:
            self.toast("Audio track saved for the next cast")


    def _update_audio_choices(self, media: streamer.MediaInfo | None) -> None:
        """Refresh a per-file audio picker without triggering a cast command."""
        picker = getattr(self, "audio_track_dropdown", None)
        if picker is None:
            return
        self._syncing = True
        try:
            tracks = media.audio_streams if media is not None else []
            picker.set_model(Gtk.StringList.new(
                ["Auto (file default)"] + [t.label for t in tracks]
            ))
            saved = self.cfg.get("audio_track_by_file") or {}
            requested = saved.get(str(media.path), -1) if media is not None and isinstance(saved, dict) else -1
            selected = next(
                (i + 1 for i, track in enumerate(tracks) if track.index == requested), 0
            )
            picker.set_selected(selected)
            picker.set_sensitive(bool(tracks))
        finally:
            self._syncing = False


    def _on_embedded_track(self, dropdown, _param) -> None:
        if self._syncing or self.media is None or self._preview_path is None:
            return
        text_tracks = [track for track in self.media.subtitle_tracks if track.is_supported]
        index = dropdown.get_selected()
        chosen = text_tracks[index - 1].index if 1 <= index <= len(text_tracks) else -1
        self.cfg.setdefault("subtitle_track_by_file", {})[self._preview_path] = chosen
        self.cfg["subs"] = "embedded"
        save_config(self.cfg)
        self._syncing = True
        self.subs_dropdown.set_selected(3)
        self._syncing = False
        self.subs_detail.set_text(self._subs_status_text())


    def _update_embedded_choices(self, media: streamer.MediaInfo) -> None:
        text_tracks = [track for track in media.subtitle_tracks if track.is_supported]
        self._syncing = True
        try:
            labels = ["Preferred embedded track"] + [track.label for track in text_tracks]
            self.embedded_dropdown.set_model(Gtk.StringList.new(labels))
            saved = self.cfg.get("subtitle_track_by_file") or {}
            selected = saved.get(str(media.path), -1) if isinstance(saved, dict) else -1
            position = next((n + 1 for n, track in enumerate(text_tracks)
                             if track.index == selected), 0)
            self.embedded_dropdown.set_selected(position)
            self.embedded_dropdown.set_visible(bool(text_tracks))
        finally:
            self._syncing = False
        self.subs_detail.set_text(self._subs_status_text())


    def _on_subs_mode(self, dropdown, _param) -> None:
        if self._syncing:
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
            dialog.open(self, None, self._subs_file_chosen)
            return
        self.cfg["subs"] = value
        save_config(self.cfg)
        self.toast("Subtitles: " + {"off": "off", "auto": "auto", "embedded": "embedded track"}[value])
        self.subs_detail.set_text(self._subs_status_text())






    def _resolve_subs(self, video: pathlib.Path) -> pathlib.Path | None:
        mode = self.cfg["subs"]
        if mode == "off":
            return None
        if mode == "pick":
            path = pathlib.Path(self.cfg["subs_path"]).expanduser()
            return path if path.is_file() and path.suffix.lower() in streamer.SUBTITLE_EXTS else None
        return streamer.find_subtitles(video) if mode == "auto" else None


    def _active_subs(self) -> str | None:
        mode = self.cfg["subs"]
        if mode == "off" or self.now_playing is None:
            return None
        if mode == "pick":
            path = pathlib.Path(self.cfg["subs_path"]).expanduser()
            return str(path) if path.is_file() else None
        return self._cached_subs(self.now_playing) if mode == "auto" else None


    def _cached_subs(self, path: str) -> str | None:
        cached_path, cached_result = self._subs_cache
        if cached_path == path:
            return cached_result
        found = streamer.find_subtitles(pathlib.Path(path))
        result = str(found) if found else None
        self._subs_cache = (path, result)
        return result


    def _subs_status_text(self) -> str:
        mode = self.cfg["subs"]
        if mode == "off":
            return "Subtitles off"
        if mode == "pick":
            path = self.cfg["subs_path"]
            return f"Using {pathlib.Path(path).name}" if path else "No subtitle file picked yet"
        if mode == "embedded" and self.media is not None:
            saved = self.cfg.get("subtitle_track_by_file") or {}
            selected = saved.get(str(self.media.path), -1) if isinstance(saved, dict) else -1
            chosen = streamer.preferred_embedded_subtitle(self.media, selected)
            return f"Embedded: {chosen.label}" if chosen else "No supported embedded text track; choose a .srt file"
        if self.now_playing:
            found = self._cached_subs(self.now_playing)
            if found:
                return f"Found next to video: {pathlib.Path(found).name}"
        if self.media is not None and self.media.subtitle_tracks:
            chosen = streamer.preferred_embedded_subtitle(self.media)
            if chosen is not None:
                return f"MKV embedded text available: {chosen.label}"
            return "Bitmap subtitles are not supported; load an .srt file"
        return "Matches an external subtitle file or selects a compatible MKV text track"


    def _on_quality(self, dropdown, _param) -> None:
        if self._syncing:
            return
        mapping = {0: "high", 1: "balanced", 2: "saver"}
        value = mapping.get(dropdown.get_selected(), "balanced")
        if value != self.cfg["quality"]:
            self.cfg["quality"] = value
            save_config(self.cfg)
            self.toast(f"Quality: {streamer.QUALITY_LABELS[value]} (restart to apply)")


    def _on_rotation(self, dropdown, _param) -> None:
        if self._syncing:
            return
        mapping = {0: 0, 1: 90, 2: 180, 3: 270}
        value = mapping.get(dropdown.get_selected(), 0)
        if value != self.cfg.get("rotation"):
            self.cfg["rotation"] = value
            save_config(self.cfg)
            self.toast(f"Video rotation {value}° (restart to apply)")


    def _on_cc_toggled(self, button) -> None:
        if self.busy or self._syncing:
            return
        on = button.get_active()
        if self._dlna_renderer() is not None:
            self._restore_cc_toggle(not on)
            self.toast("DLNA subtitles are burned into the prepared film; recast to change", error=True)
            return
        device = self._device()
        previous = self.cfg["subs"]

        def work():
            return castctl.subs_on(device) if on else castctl.subs_off(device)

        def done(result):
            ok, message = result
            if ok:
                # Persist the receiver's acknowledged state so the next status
                # refresh cannot re-derive the toggle from subtitle presence.
                self.cfg["subs"] = (
                    (previous if previous != "off" else "auto") if on else "off"
                )
                save_config(self.cfg)
            else:
                self._restore_cc_toggle(not on)
            self.toast("Captions on" if on and ok else ("Captions off" if ok else (message or "Caption toggle failed")))

        def failed(message):
            self._restore_cc_toggle(not on)
            self.toast(f"Captions failed: {message}", error=True)

        Async.run(work, done=done, failed=failed, domain="transport",
                  valid=lambda: not self._closing and self._device() == device)


    def _restore_cc_toggle(self, active: bool) -> None:
        """Put the CC toggle back without emitting a fresh receiver command."""
        self._syncing = True
        try:
            self.cc_button.set_active(active)
        finally:
            self._syncing = False


    def _start_preview(self) -> bool:
        self._preview_timer_id = 0
        if self._preview_busy or self._preview_pending is None:
            return False
        path, position, generation = self._preview_pending
        self._preview_pending = None
        if path != self._preview_path or generation != self._preview_generation:
            return False
        self._preview_busy = True

        def finish(frame=None):
            self._preview_busy = False
            latest = (path == self._preview_path
                      and generation == self._preview_generation
                      and self.session is None and not self.external
                      and self._preview_pending is None)
            # A finished decode must never overwrite a newer position the
            # user selected while FFmpeg was still extracting the old frame.
            if latest:
                if frame is not None:
                    try:
                        texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(frame))
                        self.preview_picture.set_paintable(texture)
                        self.preview_picture.set_visible(True)
                    except GLib.Error:
                        self.preview_picture.set_visible(False)
                else:
                    self.preview_picture.set_visible(False)
            if self._preview_pending is not None and not self._preview_timer_id:
                self._preview_timer_id = GLib.timeout_add(120, self._start_preview)

        media = self.media if self.media is not None and str(self.media.path) == path else None
        video_index = media.video_stream_index if media is not None else 0
        Async.run(
            lambda: screenshot.preview_frame(
                pathlib.Path(path), position, video_stream_index=video_index,
            ),
            done=finish, failed=lambda _error: finish(), domain="media",
        )
        return False


    def _queue_preview(self, position: float) -> None:
        """Debounce frame decoding, with at most one FFmpeg worker at a time."""
        if (self._preview_path is None or self.session is not None or self.external
                or self._local_stream() is not None):
            return
        self._preview_pending = (self._preview_path, max(0.0, position),
                                 self._preview_generation)
        if not self._preview_timer_id and not self._preview_busy:
            self._preview_timer_id = GLib.timeout_add(180, self._start_preview)


    def _toggle_local_preview(self) -> None:
        """Play/pause locally in the embedded video panel, never on the TV."""
        if self.session is not None or self.external:
            return
        path = self._preview_path
        if path is None:
            self.open_video()
            return
        stream = self._local_stream()
        if stream is not None and stream.get_playing():
            self._preview_position = max(0.0, stream.get_timestamp() / 1_000_000)
            stream.pause()
            self._stop_local_meter()
            self._refresh_controls()
            return
        if stream is not None and stream.get_error() is not None:
            self.toast(f"Local preview decoder: {stream.get_error().message}", error=True)
            self._unload_local_video()
            return
        if self._local_video_path != path:
            self._unload_local_video()
            self._local_start_pending = self._preview_position
            self._local_video_path = path
            self.local_video.set_file(Gio.File.new_for_path(path))
            stream = self._local_stream()
            if stream is None:
                self._unload_local_video()
                self.toast("Video backend unavailable; install GTK GStreamer media support", error=True)
                return
            stream.connect("notify::prepared", self._on_local_prepared, path)
            stream.connect("notify::error", self._on_local_error, path)
            if stream.is_prepared():
                self._on_local_prepared(stream, None, path)
        elif stream is not None and self._local_start_pending is None:
            stream.play()
            self._start_local_meter(self._preview_position)
        self.preview_picture.set_visible(False)
        self.local_video.set_visible(True)
        self._refresh_controls()


    def _local_stream(self):
        return self.local_video.get_media_stream() if self._local_video_path else None


    def _preview_monitor_chain(self) -> tuple[list, str]:
        """Meter chain and hint for the audio of the locally previewed file."""
        profile = str(self.cfg.get("audio", "dialogue"))
        gain = float(self.cfg.get("audio_gain", 0.0) or 0.0)
        mode = str(self.cfg.get("audio_loudness", "off"))
        chain, hint = streamer.monitor_summary(profile, gain, mode)
        return chain, "Local preview · " + hint


    def _start_local_meter(self, position: float) -> None:
        """Feed the line meters from the file playing in the local preview."""
        path = self._local_video_path or self._preview_path
        if path is None:
            return
        chain, hint = self._preview_monitor_chain()
        self._start_monitor(path, max(0.0, position), chain)
        self._set_levels_hint(hint)


    def _stop_local_meter(self) -> None:
        """Idle the meters when local playback stops, never a cast's meter."""
        if self._local_video_path is None:
            return
        self._stop_monitor()
        self._set_levels_hint("")


    def _meter_position(self) -> float | None:
        """Position (seconds) of the audio the meters are showing."""
        stream = self._local_stream()
        if stream is not None and self._local_video_path is not None:
            if not stream.get_playing():
                return None
            return max(0.0, stream.get_timestamp() / 1_000_000)
        return self.tracker.value()


    def _play_locally(self) -> None:
        self._toggle_local_preview()


    def _selected_path(self) -> str | None:
        if self.session is None and self._preview_path is not None:
            return self._preview_path
        if self.now_playing:
            return self.now_playing
        if self.selected_index is not None and 0 <= self.selected_index < len(self.queue):
            return self.queue[self.selected_index]
        return None


    def _current_media(self) -> streamer.MediaInfo | None:
        if self.media is not None and self.now_playing is not None and str(self.media.path) == self.now_playing:
            return self.media
        return None


    def _on_local_prepared(self, stream, _param, path: str) -> None:
        if path != self._local_video_path or not stream.is_prepared():
            return
        if self._local_start_pending is None:
            return
        start = float(self._local_start_pending)
        stream.seek(int(start * 1_000_000))
        self._local_start_pending = None
        stream.play()
        self._start_local_meter(start)
        self._record_watch("start")
        self._refresh_controls()


    def _on_local_error(self, stream, _param, path: str) -> None:
        if path != self._local_video_path:
            return
        error = stream.get_error()
        if error is not None:
            self.toast(f"Local decoder failed: {error.message}", error=True)
            self._unload_local_video()
            self.preview_picture.set_visible(False)
            self._queue_preview(self._preview_position)
            self._refresh_controls()


    def _unload_local_video(self) -> None:
        self._stop_local_meter()
        self._record_watch("stop")
        stream = self._local_stream()
        if stream is not None:
            stream.pause()
        self._local_start_pending = None
        self._local_video_path = None
        if hasattr(self, "local_video"):
            self.local_video.set_file(None)
            self.local_video.set_visible(False)


    def _start_monitor(self, media_path, offset: float, chain) -> None:
        self._stop_monitor()
        if media_path is None:
            return
        try:
            self._mon_path = pathlib.Path(media_path)
            self._mon_chain = list(chain)
            self.monitor = audio_monitor.AudioMonitor()
            track_index = -1
            if self.media is not None and self.media.path == self._mon_path:
                chosen = (self.session.state.audio_track_index
                          if self.session is not None and self.session.state is not None else -1)
                track = streamer.preferred_audio_track(self.media, chosen)
                track_index = track.index if track is not None else 0
            self.monitor.start(
                self._mon_path, self._mon_chain, offset=max(0.0, offset),
                audio_track_index=track_index,
            )
        except Exception:
            self.monitor = None


    def _stop_monitor(self, reset: bool = True) -> None:
        mon, self.monitor = self.monitor, None
        if mon is not None:
            # Stopping FFmpeg and joining its reader can take several seconds.
            # Never do that on GTK's main event loop during seek/pause/close.
            def dispose():
                try:
                    mon.stop()
                except Exception as exc:
                    print(f"SmoothCast: meter cleanup failed: {exc}", file=sys.stderr)
            threading.Thread(
                target=dispose, name="smoothcast-meter-stop", daemon=False,
            ).start()
        if reset and self.meter is not None:
            self.meter.reset()


    def _resume_monitor(self) -> None:
        if self._mon_path is None or self.media is None:
            return
        if not (self.session and self.session.active()):
            return
        pos = self.tracker.value() or 0.0
        self._start_monitor(self._mon_path, pos, self._mon_chain)


    def _meter_tick(self) -> bool:
        mon = self.monitor
        meter = self.meter
        if mon is None or meter is None:
            if meter is not None:
                meter.set_sample(None)
            return True
        position = self._meter_position()
        if position is None:
            meter.set_sample(None)
        else:
            meter.set_sample(mon.sample_at(position))
        return True


    def action_benchmark(self, *_args) -> None:
        """Measure encode speed and recommend a quality tier (SC-048 #57)."""
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
            source_fps = self.media.fps if self.media and self.media.fps else 30.0

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
        dialog.present(self)
