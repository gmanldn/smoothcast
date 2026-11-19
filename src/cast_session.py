#!/usr/bin/env python3
"""Cast sessions, transport, seeking and window modes."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk
import pathlib

from utils import pretty_title
import threading

import time

import castctl

import dlna

import streamer

import playback_state

import direct_probe

import stream_watchdog

import preflight

import url_control

from cast_widgets import DEFAULTS, save_config, fmt_time, Async


class SessionMixin:
    def cast_selected(self) -> None:
        path = None
        if self.selected_index is not None and self.selected_index < len(self.queue):
            candidate = self.queue[self.selected_index]
            if candidate != self.now_playing:
                path = candidate
        if path is None:
            path = self.now_playing
        if path is None:
            self.open_video()
            return
        start_at = self._preview_position if path == self._preview_path and self.session is None else None
        if path == self._local_video_path and self.session is None:
            stream = self._local_stream()
            if stream is not None and stream.is_prepared():
                start_at = max(0.0, stream.get_timestamp() / 1_000_000)
        self._cast_path(pathlib.Path(path), start_at)


    def _cast_path(self, path: pathlib.Path, offset: float | None = None) -> None:
        # None means "resume saved position"; explicit 0 is always rewind.
        # This avoids a seek-to-start silently jumping to a previous stop.
        offset = playback_state.start_offset(
            offset, (self.cfg.get("positions") or {}).get(str(path)),
        )
        if self.busy:
            self.toast("Hold on — finishing the last command")
            return
        # Pause and release the local decoder before starting Chromecast.
        if str(path) == self._local_video_path and self.session is None:
            stream = self._local_stream()
            if stream is not None and stream.is_prepared():
                offset = max(0.0, stream.get_timestamp() / 1_000_000)
        self._unload_local_video()
        self.local_playback.stop()
        self._preview_generation += 1
        self._preview_pending = None
        self._preview_position = offset
        self.busy = True
        self._refresh_controls()
        self._finished_handled = False
        device = self._device()
        renderer = self._dlna_renderer(device)
        self._dlna_cancel = threading.Event() if renderer is not None else None
        if renderer is not None:
            self.np_meta.set_text(
                "Preparing DLNA MP4 (may require a full-film conversion). Press Stop to cancel."
            )
            self._console(f"DLNA handoff to {renderer.name}: preparing compatible MP4")
            self._refresh_controls()
        if device.startswith("DLNA · ") and renderer is None:
            self._cast_failed("DLNA receiver is not currently discovered; scan your network again")
            return
        device_ip = self._device_host(device)
        cfg = dict(self.cfg)  # Background task must use a consistent snapshot.
        previous = self.session
        subs_mode = cfg["subs"]
        subs_path = self._resolve_subs(path)
        if subs_mode == "pick" and subs_path is None:
            self._cast_failed("Selected subtitle file is missing or unsupported; choose a valid .srt")
            return
        # Catt accepts SRT/VTT/TTML sidecars; ASS/SSA must be rendered by
        # FFmpeg rather than advertised as unsupported receiver-side tracks.
        burn = subs_path is not None and (
            bool(cfg["burn_subs"]) or subs_path.suffix.lower() not in streamer.CAST_SUBTITLE_EXTS
        )
        # Direct playback bypasses audio filters; processing requires HLS.
        speed = float(cfg.get("playback_speed", 1.0))
        rotation = streamer.normalize_rotation(cfg.get("rotation", 0))
        # A device-native stream cannot apply ffmpeg speed/rotation filters.
        # Always transcode when either transform is enabled, even for H.264/AAC.
        saved_audio = cfg.get("audio_track_by_file")
        requested_audio = (saved_audio.get(str(path), -1)
                           if isinstance(saved_audio, dict) else -1)
        audio_track = requested_audio if type(requested_audio) is int and requested_audio >= 0 else -1
        use_direct = (
            bool(cfg["direct"]) and cfg["audio"] == "original"
            and speed == 1.0 and rotation == 0 and audio_track < 0
        )

        def work():
            media = streamer.ffprobe(path)
            if audio_track >= 0 and streamer.preferred_audio_track(media, audio_track) is None:
                raise streamer.StreamError(
                    "The selected audio track is no longer in this film; choose Auto or another track"
                )
            embedded = None
            if subs_mode == "embedded" or (subs_mode == "auto" and subs_path is None):
                saved = cfg.get("subtitle_track_by_file") or {}
                requested = saved.get(str(path), -1) if isinstance(saved, dict) and subs_mode == "embedded" else -1
                embedded = streamer.preferred_embedded_subtitle(media, requested)
                if subs_mode == "embedded" and embedded is None:
                    raise streamer.StreamError(
                        "Selected embedded subtitle track is unavailable or bitmap-only; load an .srt"
                    )
            if path.suffix.lower() == ".mkv":
                # Decoder/caption failures must be reported before interrupting
                # the current receiver. One short private CPU render per file
                # fingerprint/track selection; no Cast commands in preflight.
                fingerprint = preflight.fingerprint(
                    path, audio_track_index=audio_track, subs_file=subs_path,
                    burn_subs=burn,
                    embedded_subtitle_index=embedded.index if embedded else None,
                )
                if fingerprint not in self._preflight_ok:
                    preflight.check_media(
                        media, audio_track_index=audio_track,
                        subs_file=subs_path, burn_subs=burn,
                        embedded_subtitle_index=embedded.index if embedded else None,
                    )
                    if len(self._preflight_ok) >= 256:
                        self._preflight_ok.clear()
                    self._preflight_ok.add(fingerprint)
            if self._closing:
                raise streamer.StreamError("Cast cancelled because SmoothCast is closing")
            if previous is not None:
                previous.stop(device, send_stop=previous.mode == "dlna")
            if self._closing:
                raise streamer.StreamError("Cast cancelled because SmoothCast is closing")
            session = dlna.Session() if renderer is not None else streamer.Session()
            title = pretty_title(path)
            try:
                if renderer is not None:
                    if speed != 1.0 or rotation != 0:
                        raise dlna.DlnaError(
                            "DLNA currently supports normal speed and unrotated video; reset these settings"
                        )
                    audio_choice = streamer.preferred_audio_track(media, audio_track)
                    session.start(
                        media, renderer=renderer,
                        local_ip=streamer.host_ip(renderer.host),
                        offset=offset, title=title, subtitle_file=subs_path,
                        embedded_subtitle_index=embedded.index if embedded else None,
                        audio_track=audio_choice.index if audio_choice else 0,
                        cancel=self._dlna_cancel,
                    )
                    return session, media
                if use_direct and media.direct_ok and not burn and embedded is None:
                    try:
                        session.start_direct(
                            media, device=device, subs_file=subs_path,
                            subs_disabled=(subs_mode == "off"), title=title,
                            offset=offset,
                        )
                        if direct_probe.verify_direct_start(device, title) == "rejected":
                            raise streamer.StreamError("Receiver stayed idle after direct cast; trying HLS")
                        return session, media
                    except streamer.StreamError:
                        # The failed direct attempt can leave a catt subprocess.
                        session.stop(device, send_stop=False)
                        session = streamer.Session()
                session.start_transcode(
                    media, offset, device=device, quality=cfg["quality"],
                    audio_profile=cfg["audio"], subs_file=subs_path,
                    burn_subs=burn, title=title,
                    audio_gain_db=float(cfg.get("audio_gain", DEFAULTS["audio_gain"])),
                    device_ip=device_ip,
                    speed=speed,
                    rotation=rotation,
                    embedded_subtitle_index=embedded.index if embedded is not None else None,
                    audio_track_index=audio_track,
                )
                return session, media
            except Exception:
                # No orphan ffmpeg, catt or HTTP server after failed startup.
                try:
                    session.stop(device, send_stop=False)
                except Exception:
                    pass
                raise

        def done(result):
            session, media = result
            self._cast_starting = False
            self._dlna_cancel = None
            if self._closing:
                # The hidden window and held GApplication remain alive until
                # this callback. Route through normal close policy: stop
                # the new session unless keep-streaming is enabled (DLNA
                # always stops because its HTTP server lives in this process).
                self.session = session
                self.busy = False
                self._finish_delayed_close()
                return
            self.session = session
            self.media = media
            self._update_embedded_choices(media)
            self._update_audio_choices(media)
            self.now_playing = str(path)
            if str(path) in self.queue:
                self.selected_index = self.queue.index(str(path))
            self._finished_handled = False
            self.busy = False
            started = session.state.offset if session.state else offset
            if session.mode == "transcode":
                profile = cfg["audio"]
                gain = session.state.audio_gain_db if session.state else 0.0
                chain = streamer.audio_filters(profile, gain)
                hint = streamer.AUDIO_LABELS.get(profile, profile)
                if gain > 0:
                    hint += f" · +{gain:g} dB"
            else:
                chain = []
                hint = ("DLNA progressive MP4 · original audio"
                        if session.mode == "dlna" else "Original audio (direct play)")
            self._start_monitor(media.path, started, chain)
            self._set_levels_hint(hint)
            self.tracker.start(
                started, media.duration, True,
                rate=session.state.speed if session.state else 1.0,
            )
            self._add_recent(str(path))
            self._set_now_playing_labels(media, session)
            # Update preview screen with video info.
            if self.preview is not None and media:
                bits = [media.resolution, media.vcodec]
                if media.size_label:
                    bits.append(media.size_label)
                info = " · ".join(bit for bit in bits if bit)
                self.preview.set_video(pretty_title(path), info)
            self.toast(f"Casting {pretty_title(path)} to {device}")
            self._console(f"Casting {pretty_title(path)} to {device} ({session.mode})")
            self._rebuild_queue()
            self._refresh_controls()
            self._poll_device()

        def failed(message):
            self._cast_starting = False
            if self._closing:
                self.busy = False
                self._finish_delayed_close()
                return
            # A failed preflight never stopped the previous receiver. Do not
            # discard its live meter or ownership just because a new MKV fails.
            if previous is not None and previous is self.session and previous.active():
                self.busy = False
                self.toast(f"Cast not started: {message}", error=True)
                self._console(f"Preflight/cast preparation failed: {message}")
                self._refresh_controls()
            else:
                self._cast_failed(message)

        self._cast_starting = True
        Async.run(work, done=done, failed=failed)


    def stop_stream(self) -> None:
        pos = self.tracker.value()
        if self.media is not None and pos is not None:
            self.cfg.setdefault("positions", {})[str(self.media.path)] = pos
            save_config(self.cfg)
        if self.busy:
            if self._dlna_cancel is not None:
                self._dlna_cancel.set()
                self.toast("Cancelling DLNA media preparation…")
            return
        if self.session is None and not self.external and self._preview_path is not None:
            self._unload_local_video()
            self._preview_position = 0.0
            self._queue_preview(0.0)
            self._refresh_controls()
            return
        if (self.session is None and not self.external
                and self.device_state in {"IDLE", "OFFLINE", "UNKNOWN"}):
            # Nothing owned and no observed TV playback: an idle Stop (e.g. the
            # shortcut or action before the first poll) must send no receiver
            # command, so another app's cast is never disturbed.
            self._refresh_controls()
            return
        self.busy = True
        self._refresh_controls()
        device = self._device()
        session = self.session
        self.session = None

        renderer = self._dlna_renderer(device)

        def work():
            if session is not None:
                send_stop = True
                state = session.state
                if state is not None and state.mode == "transcode":
                    # Do not stop unrelated TV content merely because our
                    # local encoder/server still has a saved session. Check
                    # receiver identity *at command time*, off the GTK thread.
                    try:
                        observed = castctl.info(device)
                    except (OSError, ValueError, TypeError):
                        observed = None
                    send_stop = playback_state.hls_session_matches(
                        observed, state.stream_url, state.title,
                    )
                session.stop(device, send_stop=send_stop)
                return send_stop
            if renderer is not None:
                dlna.stop(renderer)
            else:
                castctl.stop(device)
            return True

        def done(sent_remote_stop):
            self.busy = False
            self.tracker.clear()
            self.now_playing = None
            self._finished_handled = False
            self._stop_monitor()
            self._set_levels_hint("")
            self.toast("Stopped" if sent_remote_stop
                       else "Local stream stopped; TV content was not verified")
            self._console("Stopped casting to TV" if sent_remote_stop
                          else "Retired local stream without stopping unrelated TV content")
            self._rebuild_queue()
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=lambda msg: self._cast_failed(msg))


    def toggle_play(self) -> None:
        if self.busy:
            return
        if self.session is None and not self.external:
            self._toggle_local_preview()
            return
        if self.device_state == "OFFLINE":
            self.toast("Device is offline", error=True)
            return
        device = self._device()
        session = self.session
        renderer = self._dlna_renderer(device)
        want_play = self.device_state not in {"PLAYING", "BUFFERING"}
        # Serialize async transport, including queued shortcut/seek signals.
        self.busy = True
        self._refresh_controls()

        def current():
            return (not self._closing and self._device() == device
                    and self.session is session)

        def work():
            if renderer is not None:
                if want_play:
                    dlna.play(renderer)
                else:
                    dlna.pause(renderer)
                return True, ""
            if want_play:
                return castctl.play(device)
            return castctl.pause(device)

        def done(result):
            if not current():
                return  # Closed or replaced cast: never mutate the new UI.
            self.busy = False
            ok, message = result
            if ok:
                self.tracker.set_state(want_play)
                if want_play:
                    self._resume_monitor()
                else:
                    self._stop_monitor(reset=False)
            else:
                self.toast(message or "Command failed", error=True)
            self._refresh_controls()
            self._poll_device()

        def failed(message):
            if not current():
                return
            self.busy = False
            self.toast(f"Transport command failed: {message}", error=True)
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=failed)


    def seek_to(self, target: float) -> None:
        # Check the command lock before moving the seekbar. GTK drag signals,
        # keyboard shortcuts and programmatic actions can race a cast startup.
        if self.busy:
            self.toast("Hold on — finishing the last command")
            return
        if self.external:
            self.toast("The position of an external stream is unknown", error=True)
            return
        target = max(0.0, target)
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if self._preview_path and self.session is None and not self.external:
            duration = self.queue_durations.get(self._preview_path, duration)
        if duration:
            target = min(target, max(0.0, duration - 1.0))
        session = self.session
        if session is None and self._preview_path is not None:
            if self.seekbar is not None:
                self.seekbar.set_state(target, duration, self.seekbar.buffered)
            self._preview_position = target
            stream = self._local_stream()
            if stream is not None:
                if stream.is_prepared():
                    stream.seek(int(target * 1_000_000))
                else:
                    self._local_start_pending = target
            else:
                self._queue_preview(target)
            return
        if session is None or session.state is None:
            if self.now_playing:
                self._cast_path(pathlib.Path(self.now_playing), target)
            else:
                self.toast("Nothing is playing yet")
            return

        device = self._device()
        renderer = self._dlna_renderer(device) if session.mode == "dlna" else None
        if session.mode == "dlna" and renderer is None:
            self.toast("DLNA receiver disappeared; rescan devices", error=True)
            return
        # Optimistic seek is allowed only after all guards pass. If remote seek
        # fails, the next receiver poll reconciles the displayed film clock.
        if self.seekbar is not None:
            self.seekbar.set_state(target, duration, self.seekbar.buffered)
        if session.mode == "dlna" or (
            session.mode == "direct" and castctl.is_seekable(self.device_info)
        ):
            self.busy = True
            self._refresh_controls()
            self.tracker.device_update(target, duration)

            def current():
                return (not self._closing and self._device() == device
                        and self.session is session)

            def work():
                if renderer is not None:
                    dlna.seek(renderer, target)
                    return True, ""
                return castctl.seek(device, target)

            def done(result):
                if not current():
                    return
                self.busy = False
                ok, message = result
                if ok:
                    self.toast(f"Jumped to {fmt_time(target)}")
                else:
                    self.toast(message or "Seek failed", error=True)
                self._refresh_controls()
                self._poll_device()

            def failed(message):
                if not current():
                    return
                self.busy = False
                self.toast(f"Seek failed: {message}", error=True)
                self._refresh_controls()
                self._poll_device()

            Async.run(work, done=done, failed=failed)
            return

        self.busy = True
        self._refresh_controls()
        self.toast(f"Restarting stream at {fmt_time(target)}…")
        # Update the tracker immediately while HLS restarts; _restart_at
        # persists the requested source-film time after a successful restart.
        self.tracker.device_update(target, duration)
        self._restart_at(session, target)

    def _restart_at(self, session, target: float, *, speed_override: float | None = None,
                    audio_track_override: int | None = None) -> None:
        if session.mode == "dlna":
            # DLNA requires a fresh progressive resource if audio/codec choices
            # change; never send an HLS-specific restart to AVTransport.
            self.busy = False
            self._cast_path(pathlib.Path(session.state.file), target)
            return
        device = self._device()
        device_ip = self._device_host(device)
        state = session.state
        file_path = pathlib.Path(state.file) if state else None
        title = state.title if state else (file_path.stem if file_path else "video")
        quality = self.cfg["quality"]
        audio = self.cfg["audio"]
        speed = (
            float(speed_override) if speed_override is not None
            else float(state.speed) if state and state.speed
            else float(self.cfg.get("playback_speed", 1.0))
        )
        rotation = int(self.cfg.get("rotation", 0))
        audio_track = (
            audio_track_override if audio_track_override is not None
            else state.audio_track_index if state else -1
        )
        burn = bool(state.burn_subs) if state else False
        subs_path = None
        if state and state.subs:
            candidate = pathlib.Path(state.subs)
            subs_path = candidate if candidate.is_file() else None
        media = self.media if (self.media and file_path and self.media.path == file_path) else None
        # A restart must not silently resume a paused film. Read the intent
        # before the async worker replaces the session/tracker.
        was_paused = (self.device_state == "PAUSED"
                      or (self.tracker.known and not self.tracker.playing))

        def work():
            nonlocal media
            if media is None:
                media = streamer.ffprobe(file_path)
            session.stop(device, send_stop=False)
            try:
                session.start_transcode(
                    media, target, device=device, quality=quality,
                    audio_profile=audio, subs_file=subs_path, burn_subs=burn, title=title,
                    audio_gain_db=float(self.cfg.get("audio_gain", DEFAULTS["audio_gain"])),
                    device_ip=device_ip,
                    speed=speed,
                    rotation=rotation,
                    embedded_subtitle_index=(
                        state.embedded_subtitle_index
                        if state is not None and state.embedded_subtitle_index >= 0 else None
                    ),
                    audio_track_index=audio_track,
                )
            except Exception:
                try:
                    session.stop(device, send_stop=False)
                except Exception:
                    pass
                raise
            if was_paused:
                # start_transcode begins playback; immediately pause again so a
                # seek/speed/audio change made while paused stays paused. The
                # next device poll reconciles if pause is unsupported.
                try:
                    castctl.pause(device)
                except (OSError, ValueError, TypeError):
                    pass
            return session, media

        def done(result):
            _session, media_result = result
            self.media = media_result
            self._update_audio_choices(media_result)
            self.busy = False
            gain = _session.state.audio_gain_db if _session.state else 0.0
            chain = streamer.audio_filters(audio, gain)
            self._start_monitor(media_result.path, target, chain)
            hint = streamer.AUDIO_LABELS.get(audio, audio)
            if gain > 0:
                hint += f" · +{gain:g} dB"
            self._set_levels_hint(hint)
            self.tracker.start(target, media_result.duration, not was_paused, rate=speed)
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=self._cast_failed)


    def _skip_back1(self) -> None:
        self._skip(-1)


    def _skip_back10(self) -> None:
        self._skip(-10)


    def _skip_back30(self) -> None:
        self._skip(-30)


    def _skip_forward1(self) -> None:
        self._skip(1)


    def _skip_forward10(self) -> None:
        self._skip(10)


    def _skip_forward30(self) -> None:
        self._skip(30)


    def on_next(self) -> None:
        if self.now_playing in self.queue:
            index = self.queue.index(self.now_playing)
            if index + 1 < len(self.queue):
                self._cast_path(pathlib.Path(self.queue[index + 1]), 0.0)


    def on_prev(self) -> None:
        if self.now_playing in self.queue:
            index = self.queue.index(self.now_playing)
            if index > 0:
                # Don't change now_playing until _cast_path actually succeeds;
                # an in-flight command can reject a new cast as busy.
                self._cast_path(pathlib.Path(self.queue[index - 1]), 0.0)
                return
        if self.now_playing:
            self.seek_to(0.0)


    def _toggle_loop(self) -> None:
        """The Loop menu action changes only repeat-one, never playlist I/O."""
        self.cfg["loop"] = not bool(self.cfg.get("loop", False))
        save_config(self.cfg)
        self.toast("Repeat current video on" if self.cfg["loop"] else "Repeat off")


    def _set_speed(self, speed: float) -> None:
        speed = max(0.05, min(40.0, float(speed)))
        session = self.session
        if session is not None and session.state is not None:
            if self.busy:
                # Reject the live change without silently saving it as the
                # next-cast preference.
                self.toast("Hold on — finishing the last command")
                return
            self.cfg["playback_speed"] = speed
            save_config(self.cfg)
            self.busy = True
            self._refresh_controls()
            position = self.tracker.value() or 0.0
            duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
            self.tracker.device_update(position, duration)
            # The seekbar uses source-film time; preserve that position when
            # changing pace and restart FFmpeg at the *new* requested speed.
            self._restart_at(session, position, speed_override=speed)
            self.toast(f"Speed {speed}x — stream restarted")
        else:
            self.cfg["playback_speed"] = speed
            save_config(self.cfg)
            self.toast(f"Speed {speed}x")


    def _on_finished(self) -> None:
        self._stop_monitor()
        self._set_levels_hint("")
        item = self.now_playing
        session, self.session = self.session, None
        # Completing a movie is still a lifecycle transition: the old
        # session is tearing down its server and deleting shared HLS files.
        # Block new commands until that cleanup has finished.
        self.busy = session is not None
        self._refresh_controls()
        following = playback_state.next_media(
            item, self.queue, repeat_current=bool(self.cfg.get("loop")),
            auto_next=bool(self.cfg.get("autonext")),
            repeat_all=bool(self.cfg.get("loop_all")),
        )
        if following:
            next_path = pathlib.Path(following)
            self.now_playing = str(next_path)
            self.toast(
                f"Repeating: {next_path.name}" if following == item
                else f"Up next: {next_path.name}"
            )

            def advance(_result=None):
                # Release the guard only after the old HLS files and server
                # are gone. The fresh _cast_path acquires it again.
                self.busy = False
                self._cast_path(next_path, 0.0)

            if session is not None:
                device = self._device()
                Async.run(
                    lambda: session.stop(device, send_stop=False),
                    done=advance,
                    failed=lambda msg: self._cast_failed(f"Queue cleanup: {msg}"),
                )
            else:
                GLib.idle_add(lambda: (advance(), False)[1])
            return

        if session is not None:
            device = self._device()
            def cleaned(_result):
                self.busy = False
                if self.cfg.get("auto_shutdown"):
                    self.close()
                else:
                    self._refresh_controls()

            def failed(message):
                self.busy = False
                self.toast(f"Cleanup failed: {message}", error=True)
                self._refresh_controls()

            # The receiver already reported IDLE. Never send an extra STOP
            # that could interrupt another app's newly started playback.
            Async.run(
                lambda: session.stop(device, send_stop=False),
                done=cleaned, failed=failed,
            )
        elif self.cfg.get("auto_shutdown"):
            GLib.idle_add(lambda: (self.close(), False)[1])
        self.tracker.clear()
        self.now_playing = None
        self.toast("Finished")
        self._rebuild_queue()
        self._refresh_controls()


    def _maybe_finished(self) -> None:
        # The caster CLI/FFmpeg can finish long before the TV has drained its
        # buffer; only a confirmed PLAYING/PAUSED -> IDLE device transition ends
        # a session (direct or HLS).
        if self._finished_handled or self.busy or self.session is None:
            return
        self._finished_handled = True
        self._on_finished()


    def _tick(self) -> bool:
        previewing = self.session is None and not self.external and self._preview_path is not None
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if previewing and not duration:
            duration = self.queue_durations.get(self._preview_path, 0.0)
        position = self._preview_position if previewing else self.tracker.value()
        if previewing:
            stream = self._local_stream()
            if stream is not None and stream.is_prepared():
                if stream.get_playing() and not self.seekbar.scrubbing:
                    self._preview_position = max(0.0, stream.get_timestamp() / 1_000_000)
                    position = self._preview_position
                if not duration and stream.get_duration() > 0:
                    duration = stream.get_duration() / 1_000_000
        buffered = None
        snapshot = {}
        if self.session and self.session.mode == "transcode" and self.session.state:
            # One background snapshot feeds both the seekbar buffer and the
            # details panel, so the two never disagree within a tick.
            snapshot = self.session.progress()
            buffered = playback_state.absolute_encoded_position(
                self.session.state.offset, snapshot.get("out_time"), duration,
                speed=self.session.state.speed,
            )
        # Pure watchdog: no blocking I/O on the GTK tick.
        stream_watchdog.recover_window(self, snapshot, position)
        self.seekbar.set_state(position, duration, buffered)
        if not getattr(self.seekbar, "scrubbing", False):
            if position is not None:
                self.elapsed_label.set_text(fmt_time(position))
                if duration:
                    self.remaining_label.set_text(f"-{fmt_time(duration - position)}")
                else:
                    self.remaining_label.set_text("--:--")
            else:
                self.elapsed_label.set_text("--:--")
                self.remaining_label.set_text("--:--")
        self._update_transport_icon()
        self._update_details(snapshot)
        return True


    def _on_direct(self, switch, _param) -> None:
        self.cfg["direct"] = switch.get_active()
        save_config(self.cfg)
        self._refresh_direct_note()


    def _on_keep(self, switch, _param) -> None:
        self.cfg["keep_streaming"] = switch.get_active()
        save_config(self.cfg)


    def _on_autonext(self, switch, _param) -> None:
        self.cfg["autonext"] = switch.get_active()
        save_config(self.cfg)


    def _on_burn(self, switch, _param) -> None:
        self.cfg["burn_subs"] = switch.get_active()
        save_config(self.cfg)
        if switch.get_active():
            self.toast("Subtitles will be burned in (slower encode)")


    def _adopt_session(self) -> bool:
        state = streamer.load_session()
        if state is None:
            return False
        session = streamer.Session()
        session.restore(state)
        # Never attach to a different configured TV or issue status/control
        # requests for a saved session whose target has since changed.
        if state.device != self._device():
            return False
        # A completed encoder is no longer 'active', but its already-served
        # HLS segments may still be playing. Verify playlist/server and
        # receiver ownership asynchronously rather than on the GTK thread.
        if not session.active() and session.mode != "transcode":
            streamer.clear_session()
            return False
        # This is an *untrusted candidate* until an exact receiver URL/title
        # match and HLS availability are verified by the background worker.
        # Publishing it now would enable Stop/seek on unrelated TV content.
        if self.session is not None or getattr(self, "_adopting_session", None) is not None:
            return False
        self._adopting_session = session
        device = self._device()
        rate = state.speed if session.mode == "transcode" else 1.0
        def probe():
            current = 0.0
            info = None
            try:
                info = castctl.info(device)
                if info:
                    current = float(info.get("current_time") or 0.0)
            except (OSError, TypeError, ValueError):
                current = 0.0
            if session.mode == "direct" and not playback_state.direct_session_matches(
                info, state.title,
            ):
                return None, 0.0, info
            if session.mode == "transcode" and (
                not playback_state.hls_session_matches(info, state.stream_url, state.title)
                or (not session.active() and not session.recoverable_hls())
            ):
                return None, 0.0, info
            media = streamer.ffprobe(pathlib.Path(state.file))
            return media, current, info

        def probed(result):
            if getattr(self, "_adopting_session", None) is not session:
                return  # A newer recovery attempt superseded this one.
            self._adopting_session = None
            if (self.session is not None or self.busy or self._cast_starting
                    or self._closing or state.device != self._device()):
                return  # User changed the target or started a different cast.
            media, current, info = result
            if media is None or (
                session.mode == "direct" and not playback_state.direct_session_matches(
                    info, state.title,
                )
            ) or (
                session.mode == "transcode" and not playback_state.hls_session_matches(
                    info, state.stream_url, state.title,
                )
            ):
                # Unreachable receivers are inconclusive: retain saved state
                # for a later attempt. A definite mismatch is not ours.
                if info is not None:
                    streamer.clear_session()
                self.toast("Previous cast could not be verified")
                self._refresh_controls()
                self._poll_device()
                return
            # Only now publish ownership. No remote controls were exposed
            # before the receiver verified the saved media identity.
            self.session = session
            self.external = False
            self.now_playing = state.file
            if state.file not in self.queue:
                self.queue.append(state.file)
                self._rebuild_queue()
            elapsed = max(0.0, time.time() - state.started_at) if state.started_at else 0.0
            self.tracker.start(
                min(state.offset + elapsed * rate, state.duration or 1e18),
                state.duration, True, rate=rate,
            )
            self.toast(f"Reconnected to {pathlib.Path(state.file).name}")
            self.media = media
            if current > 0:
                absolute = (
                    playback_state.absolute_encoded_position(
                        state.offset, current, media.duration, speed=rate,
                    )
                    if session.mode == "transcode" else current
                )
                if absolute is not None:
                    self.tracker.start(
                        min(absolute, media.duration or absolute),
                        media.duration, True, rate=rate,
                    )
            gain = state.audio_gain_db
            if session.mode == "transcode":
                chain = streamer.audio_filters(state.audio, gain)
                hint = streamer.AUDIO_LABELS.get(state.audio, state.audio)
                if gain > 0:
                    hint += f" · +{gain:g} dB"
            else:
                chain = []
                hint = "Original audio (direct play)"
            position = self.tracker.value() or state.offset
            self._start_monitor(media.path, position, chain)
            self._set_levels_hint(hint)
            self._set_now_playing_labels(media, session)
            self._poll_device()

        def failed(message):
            if getattr(self, "_adopting_session", None) is session:
                self._adopting_session = None
            self._console(f"Saved cast inspection failed: {message}")

        Async.run(probe, done=probed, failed=failed)
        self._refresh_controls()
        self._poll_device()
        return False


    def _cast_remote_url(self, value: str) -> None:
        # The external URL workflow is a catt/Google Cast capability, not a
        # DLNA AVTransport resource negotiation path. Do not issue catt
        # commands to a DLNA identifier or discard the current DLNA session.
        if self._dlna_renderer() is not None:
            self.toast("Open URL currently requires a Google Cast target; choose Cast or open a local film", error=True)
            return
        try:
            url = url_control.validate_media_url(value)
        except ValueError as exc:
            self.toast(str(exc), error=True)
            return
        if self.busy:
            self.toast("Hold on — finishing the last command")
            return
        device = self._device()
        previous = self.session
        self.session = None
        self.busy = True
        self._refresh_controls()
        self.toast(f"Opening remote stream on {device}…")

        def work():
            if previous is not None:
                previous.stop(device, send_stop=False)
            # catt casts HTTP(S) URLs directly, resolving supported video
            # sites. Do not send remote URLs through local-file ffprobe.
            return castctl.command(device, "cast", "--no-subs", url, timeout=60)

        def done(result):
            ok, message = result
            self.busy = False
            if not ok:
                self._cast_failed(message or "Remote cast failed")
                return
            self._stop_monitor()
            # A successful handoff must release the local decoder/player so the
            # machine's own audio does not keep playing under the TV cast.
            self._unload_local_video()
            self.local_playback.stop()
            self.media = None
            self.now_playing = None
            self.external = True
            self._url_cast_url = url
            self._url_cast_seen = False
            self.tracker.clear()
            self.np_title.set_text("Remote stream")
            self.toast(f"Remote stream sent to {device}")
            self._console(f"Remote stream sent to {device}")
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=self._cast_failed)


    def _open_url(self) -> None:
        dialog = Adw.AlertDialog.new("Open URL", "Paste a stream URL")
        entry = Gtk.Entry()
        entry.set_placeholder_text("https://...")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("open", "Open")
        dialog.set_default_response("open")
        dialog.set_response_appearance("open", Adw.ResponseAppearance.SUGGESTED)
        def on_resp(d, r):
            if r == "open":
                url = entry.get_text().strip()
                if url:
                    self._cast_remote_url(url)
        dialog.connect("response", on_resp)
        dialog.present(self)


    def _toggle_fullscreen(self) -> None:
        self._remember_normal_geometry()
        # Gtk4 exposes fullscreen()/unfullscreen(), not set_fullscreen().
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()


    def _toggle_theater(self) -> None:
        self._remember_normal_geometry()
        if self.is_maximized():
            self.unmaximize()
        else:
            self.maximize()
        self.toast("Theater mode " + ("on" if self.is_maximized() else "off"))


    def _sleep_timer(self, minutes: int) -> None:
        minutes = max(0, int(minutes))
        self.cfg["sleep_timer_minutes"] = minutes
        self.cfg["sleep_timer_deadline"] = playback_state.sleep_deadline(
            time.time(), minutes,
        )
        save_config(self.cfg)
        self.toast(
            f"Sleep timer armed: {minutes} min" if minutes
            else "Sleep timer cancelled"
        )


    def _sleep_tick(self) -> bool:
        deadline = self.cfg.get("sleep_timer_deadline", 0.0)
        if not playback_state.timer_expired(deadline, time.time()):
            return True
        if self.busy:
            return True  # Do not interrupt an in-flight cast command.
        self.cfg["sleep_timer_deadline"] = 0.0
        self.cfg["sleep_timer_minutes"] = 0
        save_config(self.cfg)
        if self.session is not None:
            self.toast("Sleep timer expired — stopping cast")
            self.stop_stream()
        elif self._url_cast_url is not None:
            self._sleep_stop_url_cast()
        else:
            self.toast("Sleep timer expired")
        return True


    def _sleep_stop_url_cast(self) -> None:
        """Stop our own URL cast at the deadline, never a replacement.

        A URL cast has no local Session. Re-check the receiver off the GTK
        thread at command time and stop only if it still reports the exact URL
        we sent; if another app replaced it, leave that content playing.
        """
        device = self._device()
        saved_url = self._url_cast_url or ""
        self.busy = True
        self._refresh_controls()

        def work():
            try:
                observed = castctl.info(device)
            except (OSError, ValueError, TypeError):
                observed = None
            if not playback_state.url_cast_matches(observed, saved_url):
                return False
            ok, _ = castctl.stop(device)
            return ok

        def done(stopped):
            self.busy = False
            self._url_cast_url = None
            self._url_cast_seen = False
            if stopped:
                self.external = False
                self.tracker.clear()
                self.now_playing = None
                self._finished_handled = False
                self.toast("Sleep timer expired — stopped the URL cast")
            else:
                self.toast("Sleep timer expired; left the current TV content playing")
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=self._cast_failed)


    def _toggle_auto_shutdown(self) -> None:
        self.cfg["auto_shutdown"] = not self.cfg.get("auto_shutdown", False)
        save_config(self.cfg)
        self.toast("Auto-shutdown " + ("on" if self.cfg["auto_shutdown"] else "off"))


    def _toggle_auto_theme(self) -> None:
        self.cfg["auto_theme"] = not self.cfg.get("auto_theme", False)
        save_config(self.cfg)
        self._apply_color_scheme()
        self.toast("Auto theme " + ("on" if self.cfg["auto_theme"] else "off"))


    def _cast_failed(self, message: str) -> None:
        self._dlna_cancel = None
        self.busy = False
        self._stop_monitor()
        self._set_levels_hint("")
        if self.session is not None and not self.session.active():
            self.session = None
        if self.session is None:
            self.tracker.clear()
            self._finished_handled = False
        self.toast(f"Cast failed: {message}", error=True)
        self._console(f"Cast failed: {message}")
        self._refresh_controls()


    def _skip(self, delta: float) -> None:
        position = (self._preview_position if self.session is None and self._preview_path is not None
                    and not self.external else self.tracker.value())
        if position is None:
            self.toast("Position unknown — nothing to skip in")
            return
        self.seek_to(position + delta)
