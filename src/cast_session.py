#!/usr/bin/env python3
"""Cast sessions, transport, seeking and window modes."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib
import pathlib

from async_jobs import UserFacingError
from cast_ab_repeat_ui import AbRepeatUiMixin
from cast_remote_url import RemoteUrlCastMixin
from utils import pretty_title
import threading

import time

import capability_gate
import cast_recovery
import castctl
import command_trace

import dlna

import streamer
import low_end_policy

import audio_delay
import subtitle_delay
import subtitle_style

import subtitle_restart

import playback_state

import watch_history

import progress_model

import direct_probe
import receiver_memory

import stream_watchdog

import hls_pause_recovery
import fingerprint
import hdr_tonemap
import picture_adjustments

import preflight
import queue_metadata
import reliability_metrics

import cast_failure_code

from cast_widgets import DEFAULTS, CONFIG_DIR, save_config, fmt_time, Async


class SessionMixin(AbRepeatUiMixin, RemoteUrlCastMixin):
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


    def _cast_path(self, path: pathlib.Path, offset: float | None = None) -> str | None:
        """Submit cast preparation; return a safe reason for immediate rejection.

        None means the background preparation was submitted, not that the
        receiver is playing. Desktop callers already receive toast feedback.
        """
        # None resumes; zero rewinds.
        offset = playback_state.start_offset(
            offset, watch_history.saved_position(
                self.cfg, path, fingerprint.KEYS.get(path)))
        if self.busy:
            reason = "Hold on — finishing the last command"
            self.toast(reason)
            return reason
        if not self._device().strip():
            reason = "Choose a room receiver before casting"
            self.toast(reason, error=True)
            return reason
        self._last_cast_path = path  # for the failure toast's one-click retry
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
        self._finished_handled = False
        device = self._device()
        self._cast_feedback = {"receiver": device, "state": "preparing",
                               "message": "Preparing media and connecting to the room receiver."}
        renderer = self._dlna_renderer(device)
        reliability_metrics.start_attempt(self, "dlna" if renderer is not None else "cast")
        cancel = threading.Event()
        self._dlna_cancel = cancel
        if renderer is not None:
            self.np_meta.set_text(
                "Preparing DLNA MP4 (may require a full-film conversion). Press Stop to cancel."
            )
            self._console(f"DLNA handoff to {renderer.name}: preparing compatible MP4")
        # Publish cancellability for Cast as well as DLNA before worker submission.
        self._refresh_controls()
        if device.startswith("DLNA · ") and renderer is None:
            reason = "DLNA receiver is not currently discovered; scan your network again"
            self._cast_preflight_failed(reason)
            return reason
        device_ip = self._device_host(device)
        cfg = dict(self.cfg)  # Background task must use a consistent snapshot.
        previous = self.session
        prewarmed_entry = getattr(self, "_media_cache", {}).get(str(path))
        display_name = getattr(self, "_portal_queue_display_names", {}).get(str(path))
        subs_mode = cfg["subs"]
        # Keep immediate validation of an explicitly selected subtitle, but
        # defer automatic directory scanning to the cast worker.
        picked_subs_path = self._resolve_subs(path) if subs_mode == "pick" else None
        if subs_mode == "pick" and picked_subs_path is None:
            reason = "Selected subtitle file is missing or unsupported; choose a valid .srt"
            self._cast_preflight_failed(reason)
            return reason
        delay = subtitle_delay.get(cfg, path)
        adelay = audio_delay.get(cfg, path)
        preset = subtitle_style.from_config(cfg)
        speed = float(cfg.get("playback_speed", 1.0))
        rotation = streamer.normalize_rotation(cfg.get("rotation", 0))
        aspect_mode = cfg.get("aspect_override", "original")
        saved_audio = cfg.get("audio_track_by_file")
        requested_audio = (saved_audio.get(str(path), -1)
                           if isinstance(saved_audio, dict) else -1)
        audio_track = requested_audio if type(requested_audio) is int and requested_audio >= 0 else -1
        learned = receiver_memory.ReceiverMemory(CONFIG_DIR / receiver_memory.STATE_NAME)
        picture_config = picture_adjustments.for_path(cfg, path)
        use_direct = (
            bool(cfg["direct"]) and cfg["audio"] == "original"
            and speed == 1.0 and rotation == 0 and audio_track < 0 and not adelay
            and not picture_adjustments.active(picture_config)
            and not getattr(self, "_portal_early", False)
            and not getattr(self, "_force_transcode_once", False)
        )
        self._force_transcode_once = False  # one-shot override from the retry button
        self._attempt_mode = "direct" if use_direct else "transcode"
        if not getattr(self, "_retry_in_flight", False):
            self._cast_tried = []  # a fresh user-initiated cast starts a new attempt history
        self._retry_in_flight = False
        def work():
            if cancel.is_set():
                raise streamer.StreamError("Cast cancelled before receiver handoff")
            subs_path = (self._resolve_subs(path, config=cfg)
                         if subs_mode == "auto" else picked_subs_path)
            if cancel.is_set():
                raise streamer.StreamError("Cast cancelled before receiver handoff")
            burn = subs_path is not None and (
                bool(cfg["burn_subs"]) or subs_path.suffix.lower() not in streamer.CAST_SUBTITLE_EXTS
                or delay != 0 or preset != subtitle_style.DEFAULT
            )
            media, prewarm_fingerprint = queue_metadata.media_for_cast(
                prewarmed_entry, path, streamer.ffprobe,
            )
            if cancel.is_set():
                raise streamer.StreamError("Cast cancelled before receiver handoff")
            streamer.require_compatible_ffmpeg()
            # Reject an FFmpeg without HDR filters before stopping an owned cast.
            try:
                hdr_tonemap.require_available(media)
            except hdr_tonemap.TonemapUnavailable as exc:
                raise streamer.StreamError(str(exc)) from exc
            effective_subs_path, effective_burn = streamer.audio_cast_options(
                media, subs_mode, subs_path, burn, dlna=renderer is not None)
            if audio_track >= 0 and streamer.preferred_audio_track(media, audio_track) is None:
                raise UserFacingError(
                    "The selected audio track is no longer in this film. Choose Auto or another track.",
                    code="media.audio_track_missing",
                )
            music_enabled = streamer.schedule_music_analysis(
                path, media, audio_track, self, cfg)
            embedded = None
            if subs_mode == "embedded" or (subs_mode == "auto" and subs_path is None):
                saved = cfg.get("subtitle_track_by_file") or {}
                requested = saved.get(str(path), -1) if isinstance(saved, dict) and subs_mode == "embedded" else -1
                embedded = streamer.preferred_embedded_subtitle(media, requested)
                if subs_mode == "embedded" and embedded is None:
                    raise UserFacingError(
                        "The selected subtitle track is unavailable. Choose another track or turn subtitles off.",
                        code="subtitle.unavailable",
                    )
            if path.suffix.lower() == ".mkv":
                # Report caption/decoder failures before touching the receiver.
                fingerprint = preflight.fingerprint(
                    path, audio_track_index=audio_track, subs_file=effective_subs_path,
                    burn_subs=effective_burn,
                    embedded_subtitle_index=embedded.index if embedded else None,
                )
                if fingerprint not in self._preflight_ok:
                    preflight.check_media(
                        media, audio_track_index=audio_track,
                        subs_file=effective_subs_path, burn_subs=effective_burn,
                        embedded_subtitle_index=embedded.index if embedded else None,
                    )
                    if len(self._preflight_ok) >= 256:
                        self._preflight_ok.clear()
                    self._preflight_ok.add(fingerprint)
            if renderer is not None:
                if speed != 1.0 or rotation != 0:
                    raise UserFacingError(
                        "This receiver needs normal speed and unrotated video. Reset those settings and try again.",
                        code="cast.settings_unsupported",
                    )
                try:
                    media_type = dlna.negotiate_media_type(renderer)
                except dlna.DlnaError as exc:
                    raise UserFacingError(
                        "The receiver advertises no supported MP4 or MPEG-TS format. Choose another receiver.",
                        code="cast.no_supported_format",
                    ) from exc
                if cancel.is_set():
                    raise dlna.DlnaError("DLNA preparation cancelled")
            if self._closing:
                raise streamer.StreamError("Cast cancelled because SmoothCast is closing")
            if cancel.is_set():
                raise streamer.StreamError("Cast cancelled before replacing current playback")
            if (prewarm_fingerprint is not None and
                    queue_metadata.file_fingerprint(path) != prewarm_fingerprint):
                raise UserFacingError("The queued film changed. Try casting it again.", code="media.changed")
            if previous is not None:
                previous.stop(device, send_stop=previous.mode == "dlna")
            if cancel.is_set():
                raise streamer.StreamError("Cast cancelled before receiver handoff")
            if self._closing:
                raise streamer.StreamError("Cast cancelled because SmoothCast is closing")
            session = dlna.Session() if renderer is not None else streamer.Session()
            title = queue_metadata.media_title(path, media, display_name, fallback=pretty_title(path))

            def stop_if_cancelled_after_start():
                if cancel.is_set():
                    session.stop(device, send_stop=True)
                    raise streamer.StreamError("Cast cancelled during receiver handoff")

            try:
                if renderer is not None:
                    audio_choice = streamer.preferred_audio_track(media, audio_track)
                    session.start(
                        media, renderer=renderer,
                        local_ip=streamer.host_ip(renderer.host),
                        offset=offset, title=title, subtitle_file=subs_path,
                        embedded_subtitle_index=embedded.index if embedded else None,
                        audio_track=audio_choice.index if audio_choice else 0,
                        subtitle_delay_ms=delay, audio_delay_ms=adelay,
                        cancel=cancel, audio_profile=cfg["audio"], media_type=media_type,
                        **({"aspect_mode": aspect_mode} if aspect_mode != "original" else {}),
                    )
                    stop_if_cancelled_after_start()
                    return session, media
                receiver_key = codec_key = ""
                if renderer is None:
                    try:
                        receiver_key = receiver_memory.receiver_key(
                            uuid=str(cfg.get("device_uuid") or ""), host=device_ip, port=8009)
                        codec_key = receiver_memory.media_signature(
                            media, container=path.suffix.lower().lstrip("."),
                            subtitle_kind=("sidecar" if effective_subs_path else
                                           "embedded" if embedded else "none"))
                    except ValueError:
                        # No stable identity or codec: keep the normal direct decision, and
                        # drop the half-built key so nothing is recorded under it later.
                        receiver_key = codec_key = ""
                gate_ok, _gate_note = capability_gate.direct_allowed(
                    media, path.suffix, next((d.model for d in getattr(self, "devices", ()) if d.name == device), ""))
                direct_eligible = (
                    use_direct and media.direct_ok and not burn and gate_ok
                    and embedded is None and not music_enabled
                    and (aspect_mode == "original" or getattr(media, "is_audio_only", False)))
                if receiver_memory.should_try_direct(
                        direct_eligible, learned, receiver_key, codec_key):
                    try:
                        session.start_direct(
                            media, device=device, subs_file=subs_path,
                            subs_disabled=(subs_mode == "off"), title=title,
                            offset=offset,
                        )
                        outcome = direct_probe.verify_direct_start(device, title)
                        if outcome == "rejected":
                            if receiver_key:
                                learned.record(receiver_key, codec_key, "direct", False)
                            raise streamer.StreamError("Receiver stayed idle after direct cast; trying HLS")
                    except streamer.StreamError as exc:
                        # Another media format cannot fix a receiver that never
                        # returned status. Avoid a second long, doomed handoff.
                        if getattr(exc, "code", None) == "cast.receiver_offline":
                            raise
                        # The failed direct attempt can leave a catt subprocess.
                        session.stop(device, send_stop=False)
                        session = streamer.Session()
                    else:
                        stop_if_cancelled_after_start()
                        if outcome == "accepted" and receiver_key:
                            learned.record(receiver_key, codec_key, "direct", True)
                        return session, media
                session.start_transcode(
                    media, offset, device=device,
                    quality=low_end_policy.effective_quality(cfg, media),
                    audio_profile=cfg["audio"], subs_file=effective_subs_path,
                    burn_subs=effective_burn, title=title,
                    audio_gain_db=float(cfg.get("audio_gain", DEFAULTS["audio_gain"])),
                    audio_loudness=str(cfg.get("audio_loudness", "off")),
                    device_ip=device_ip,
                    speed=speed,
                    rotation=rotation,
                    **({"aspect_mode": aspect_mode} if aspect_mode != "original" else {}),
                    embedded_subtitle_index=embedded.index if embedded is not None else None,
                    audio_track_index=audio_track,
                    subtitle_delay_ms=delay, subtitle_preset=preset,
                    audio_delay_ms=adelay,
                    music_autogain=music_enabled,
                    picture_config=picture_config,
                )
                # start_transcode returned only after verifying our HLS URL on
                # the receiver; a successful FFmpeg/catt launch alone is not proof.
                stop_if_cancelled_after_start()
                if receiver_key:
                    learned.record(receiver_key, codec_key, "hls", True)
                return session, media
            except Exception:
                # Preserve the startup failure; cleanup must not replace it.
                try:
                    session.stop(device, send_stop=False)
                except Exception:  # noqa: BLE001 - cleanup cannot mask startup failure
                    pass
                raise

        def done(result):
            session, media = result
            self._cast_feedback = {"receiver": device, "state": "confirmed",
                                   "message": "Receiver confirmed playback."}
            self._cast_starting = False
            self._dlna_cancel = None
            if self._closing:
                self.session = session
                reliability_metrics.accept_attempt(self, session, Async.run)
                reliability_metrics.finish_active(self, "interrupted", Async.run)
                self.busy = False
                self._finish_delayed_close()
                return
            reliability_metrics.accept_attempt(self, session, Async.run)
            if (getattr(self, "_preview_path", None) != str(path)
                    and hasattr(self, "_reset_ab_repeat")):
                self._reset_ab_repeat()
            self.session = session
            self.media = media
            self._update_embedded_choices(media)
            self._update_audio_choices(media)
            self.now_playing = str(path)
            self.menu_button.set_menu_model(self._build_menu())
            if str(path) in self.queue:
                self.selected_index = self.queue.index(str(path))
            self._finished_handled = False
            self.busy = False
            started = session.state.offset if session.state else offset
            if session.mode == "transcode":
                profile = cfg["audio"]
                gain = session.state.audio_gain_db if session.state else 0.0
                chain, hint = streamer.monitor_summary(
                    profile, gain, streamer.state_loudness(session.state))
            else:
                chain = []
                hint = ("DLNA progressive MP4"
                        if session.mode == "dlna" else "Original audio (direct play)")
                hint = streamer.music_hint_not_applied(hint, media, cfg)
            self._start_monitor(media.path, started, chain)
            self._set_levels_hint(hint)
            self.tracker.start(
                started, media.duration, True,
                rate=session.state.speed if session.state else 1.0,
            )
            self._add_recent(str(path))
            self._note_device_used()
            self._record_watch("start")
            self._set_now_playing_labels(media, session)
            # Keep the confirmed receiver title on every playback surface.
            title = self.np_title.get_text()
            # Refresh preview metadata.
            if self.preview is not None and media:
                info = streamer.media_summary(media)
                if media.size_label:
                    info += f" · {media.size_label}"
                self.preview.set_video(title, info)
            self.toast(f"Casting {title} to {device}")
            self._console(f"Casting {title} to {device} ({session.mode})")
            self._rebuild_queue()
            self._refresh_controls()
            self._poll_device()

        def failed(message):
            self._cast_feedback = {
                "receiver": device, "state": "cancelled" if cancel.is_set() else "failed",
                "message": "Playback preparation cancelled." if cancel.is_set() else message,
            }
            self._cast_starting = False
            self._dlna_cancel = None
            reliability_metrics.fail_attempt(self, Async.run)
            if self._closing:
                self.busy = False
                self._finish_delayed_close()
                return
            # Preserve the prior session on preflight failure.
            if previous is not None and previous is self.session and previous.active():
                self.busy = False
                self.toast(f"Cast not started: {message}", error=True)
                self._console(f"Preflight/cast preparation failed: {message}")
                self._refresh_controls()
            else:
                self._cast_failed(message)

        self._cast_starting = True
        Async.run(work, done=done, failed=failed, domain="cast_start")
        return None


    @command_trace.traced("desktop", "stop")
    def stop_stream(self) -> None:
        if hasattr(self, "_reset_ab_repeat"):
            self._reset_ab_repeat()
        pos = self.tracker.value()
        if self.media is not None and pos is not None:
            self.cfg.setdefault("positions", {})[str(self.media.path)] = pos
            save_config(self.cfg)
        if self.busy:
            if self._dlna_cancel is not None:
                self._dlna_cancel.set()
                self.toast("Cancelling cast setup before receiver handoff…")
            return
        if self.session is None and not self.external and self._preview_path is not None:
            self._unload_local_video()
            self._preview_position = 0.0
            self._queue_preview(0.0)
            self._refresh_controls()
            return
        if (self.session is None and not self.external
                and self.device_state in {"IDLE", "OFFLINE", "UNKNOWN"}):
            self._refresh_controls()
            return
        self._record_watch("stop")
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
                    # Verify receiver ownership off the GTK thread before Stop.
                    try:
                        observed = castctl.info(device)
                    except (OSError, ValueError, TypeError):
                        observed = None
                    send_stop = playback_state.hls_session_matches(
                        observed, state.stream_url, state.title,
                    )
                return bool(session.stop(device, send_stop=send_stop))
            if renderer is not None:
                dlna.stop(renderer)
                return True
            ok, _message = castctl.stop(device)
            return bool(ok)

        def done(sent_remote_stop):
            reliability_metrics.finish_active(
                self, "stopped" if sent_remote_stop else "interrupted", Async.run,
            )
            self.busy = False
            self.tracker.clear()
            self.now_playing = None
            self._finished_handled = False
            self._stop_monitor()
            self._set_levels_hint("")
            self.toast("Stopped" if sent_remote_stop
                       else "Local stream stopped; receiver did not confirm Stop")
            self._console("Stopped casting to TV" if sent_remote_stop
                          else "Retired local stream without receiver Stop confirmation")
            self._rebuild_queue()
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=lambda msg: self._cast_failed(msg), domain="transport")


    @command_trace.traced("desktop", "play_pause")
    def toggle_play(self) -> None:
        if self.busy:
            return
        if self.session is None and not self.external:
            self._toggle_local_preview()
            return
        if self.device_state == "OFFLINE":
            self.toast("Receiver offline. Check its power and network connection.", error=True)
            return
        device = self._device()
        session = self.session
        renderer = self._dlna_renderer(device)
        want_play = self.device_state not in {"PLAYING", "BUFFERING"}
        if hls_pause_recovery.resume_from_long_pause(self, session, device, renderer, want_play):
            return
        # Serialize transport commands.
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

        Async.run(work, done=done, failed=failed, domain="transport")


    @command_trace.traced("desktop", "seek")
    def seek_to(self, target: float, *, feedback_label: str | None = None,
                exact_source_time: bool = False) -> None:
        # Guard before seekbar moves.
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
            target = min(target, max(0.0, duration if exact_source_time
                                     else duration - 1.0))
        repeat = getattr(self, "ab_repeat", None)
        if repeat is not None:
            repeat.manual_seek(target)
        session = self.session
        if session is None and self._preview_path is not None:
            if self.seekbar is not None:
                self.seekbar.set_state(target, duration, self.seekbar.buffered)
            self._preview_position = target
            self.elapsed_label.set_text(fmt_time(target))
            self.remaining_label.set_text(f"-{fmt_time(max(0.0, duration - target))}" if duration else "--:--")
            stream = self._local_stream()
            if stream is not None:
                if stream.is_prepared():
                    stream.seek(int(target * 1_000_000))
                else:
                    self._local_start_pending = target
            else:
                self._queue_preview(target)
            if feedback_label:
                self.toast(f"{feedback_label} — {fmt_time(target)} (local preview)")
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
        # Poll to reconcile failed seeks.
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
                    self.toast(f"{feedback_label} — {fmt_time(target)}" if feedback_label
                               else f"Jumped to {fmt_time(target)}")
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

            Async.run(work, done=done, failed=failed, domain="transport")
            return

        self.busy = True
        self._refresh_controls()
        self.toast(f"{feedback_label} — seeking…" if feedback_label
                   else f"Restarting stream at {fmt_time(target)}…")
        self.tracker.device_update(target, duration)
        self._restart_at(session, target, feedback_label=feedback_label)

    def _restart_at(self, session, target: float, *, speed_override: float | None = None,
                    audio_track_override: int | None = None,
                    resume_after_pause: bool = False,
                    feedback_label: str | None = None) -> None:
        if session.mode == "dlna":
            self.busy = False
            self._cast_path(pathlib.Path(session.state.file), target)
            return
        device = self._device()
        device_ip = self._device_host(device)
        state = session.state
        file_path = pathlib.Path(state.file) if state else None
        title = state.title if state else (file_path.stem if file_path else "video")
        cfg = dict(self.cfg)  # frozen before background restart
        picture_config = picture_adjustments.for_path(cfg, file_path)
        audio = self.cfg["audio"]
        speed = (
            float(speed_override) if speed_override is not None
            else float(state.speed) if state and state.speed
            else float(self.cfg.get("playback_speed", 1.0))
        )
        rotation = int(self.cfg.get("rotation", 0))
        aspect_mode = getattr(state, "aspect_mode", "original")
        audio_track = (
            audio_track_override if audio_track_override is not None
            else state.audio_track_index if state else -1
        )
        delay = subtitle_delay.get(self.cfg, file_path)
        # Validate captions before teardown.
        media = self.media if (self.media and file_path and self.media.path == file_path) else None
        was_paused = (not resume_after_pause and
                      (self.device_state == "PAUSED" or
                       (self.tracker.known and not self.tracker.playing)))

        def work():
            nonlocal media
            if media is None:
                media = streamer.ffprobe(file_path)
            captions = subtitle_restart.validate_restart(state, media, delay)
            streamer.require_compatible_ffmpeg()
            session.stop(device, send_stop=False)
            try:
                session.start_transcode(
                    media, target, device=device,
                    quality=low_end_policy.effective_quality(cfg, media),
                    audio_profile=audio, subs_file=captions.external,
                    burn_subs=captions.burn, title=title,
                    audio_gain_db=float(self.cfg.get("audio_gain", DEFAULTS["audio_gain"])),
                    audio_loudness=str(self.cfg.get("audio_loudness", "off")),
                    device_ip=device_ip,
                    speed=speed,
                    rotation=rotation,
                    **({"aspect_mode": aspect_mode} if aspect_mode != "original" else {}),
                    embedded_subtitle_index=captions.embedded_index,
                    audio_track_index=audio_track,
                    subtitle_delay_ms=captions.delay_ms,
                    subtitle_preset=subtitle_style.from_config(self.cfg),
                    audio_delay_ms=audio_delay.get(self.cfg, file_path),
                    music_autogain=bool(self.cfg.get("music_autogain", False)),
                    picture_config=picture_config,
                )
            except Exception:
                # Preserve the startup failure; cleanup must not replace it.
                try:
                    session.stop(device, send_stop=False)
                except Exception:  # noqa: BLE001 - cleanup cannot mask startup failure
                    pass
                raise
            if was_paused:
                # Preserve pause.
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
            chain, hint = streamer.monitor_summary(
                audio, gain, streamer.state_loudness(_session.state))
            self._start_monitor(media_result.path, target, chain)
            self._set_levels_hint(hint)
            self.tracker.start(target, media_result.duration, not was_paused, rate=speed)
            if self.session is _session and not self._closing:
                if feedback_label:
                    self.toast(f"{feedback_label} — {fmt_time(target)}")
                elif speed_override is not None:
                    self.toast(f"Speed {speed:g}x applied")
            self._refresh_controls()
            self._poll_device()

        def failed(message):
            if self.session is session and session.active():
                self.busy = False
                self.toast(f"Restart cancelled: {message}", error=True)
                self._console(f"Original cast preserved: {message}")
                self._refresh_controls()
            else:
                self._cast_failed(message)

        Async.run(work, done=done, failed=failed, domain="media")


    def _skip_back1(self) -> None:
        self._frame_step(-1)


    def _skip_back10(self) -> None:
        self._skip(-10)


    def _skip_back30(self) -> None:
        self._skip(-30)


    def _skip_forward1(self) -> None:
        self._frame_step(1)


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
                # Keep now_playing unchanged until cast acceptance.
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
                # Reject live changes without saving them.
                self.toast("Hold on — finishing the last command")
                return
            self.cfg["playback_speed"] = speed
            save_config(self.cfg)
            self.busy = True
            self._refresh_controls()
            position = self.tracker.value() or 0.0
            duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
            self.tracker.device_update(position, duration)
            # Preserve source time when changing playback speed.
            self.toast(f"Applying speed {speed:g}x…")
            self._restart_at(session, position, speed_override=speed)
        else:
            self.cfg["playback_speed"] = speed
            save_config(self.cfg)
            self.toast(f"Speed {speed}x")


    def _on_finished(self) -> None:
        if hasattr(self, "_reset_ab_repeat"):
            self._reset_ab_repeat()
        reliability_metrics.finish_active(self, "completed", Async.run)
        self._record_watch("completed")
        self._stop_monitor()
        self._set_levels_hint("")
        item = self.now_playing
        session, self.session = self.session, None
        # Block new commands until the old HLS server and media are cleaned up.
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
                # Release the guard only after old stream cleanup.
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

            # Don't stop after confirmed IDLE; another app may have started.
            Async.run(
                lambda: session.stop(device, send_stop=False),
                done=cleaned, failed=failed,
            )
        elif self.cfg.get("auto_shutdown"):
            GLib.idle_add(lambda: (self.close(), False)[1])
        self.tracker.clear()
        self.now_playing = None
        self.toast("Finished")
        self._notify("finished", item or "")
        self._rebuild_queue()
        self._refresh_controls()


    def _maybe_finished(self) -> None:
        # Device IDLE confirms end; FFmpeg exit does not.
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
        if self.external:
            position, duration = self._portal_timing()
        if previewing:
            stream = self._local_stream()
            if stream is not None and stream.is_prepared():
                if stream.get_playing() and not self.seekbar.scrubbing and not stream.is_seeking():
                    self._preview_position = max(0.0, stream.get_timestamp() / 1_000_000)
                    position = self._preview_position
                if not duration and stream.get_duration() > 0:
                    duration = stream.get_duration() / 1_000_000
        buffered = None
        snapshot = progress_model.EMPTY
        if self.session and self.session.mode == "transcode" and self.session.state:
            # Reuse one snapshot for the seekbar and details.
            snapshot = self.session.progress()
            buffered = playback_state.absolute_encoded_position(
                self.session.state.offset, snapshot.out_time, duration,
                speed=self.session.state.speed,
            )
        # Pure watchdog: no blocking I/O on the GTK tick.
        stream_watchdog.recover_window(self, snapshot, position)
        self.seekbar.set_state(position, duration, buffered,
                               unknown_length=self.external and position is not None)
        if position is not None:
            local_stream = self._local_stream() if previewing else None
            playing = (bool(local_stream and local_stream.get_playing())
                       if previewing else self.tracker.playing)
            playing = playing and not self.busy and not self.external
            target = self.ab_repeat.boundary_target(position, playing=playing)
            if target is not None:
                self.seek_to(target, feedback_label="A–B repeat", exact_source_time=True)
            elif previewing and duration and position >= duration:
                self._reset_ab_repeat()
        if not getattr(self.seekbar, "scrubbing", False):
            if position is not None:
                self.elapsed_label.set_text(fmt_time(position))
                if duration:
                    self.remaining_label.set_text(f"-{fmt_time(duration - position)}")
                else:
                    self.remaining_label.set_text("Live" if self.external else "--:--")
            else:
                self.elapsed_label.set_text("--:--")
                self.remaining_label.set_text("--:--")
        self._update_transport_icon()
        self._update_details(snapshot)
        self._publish_portal_status()
        return True


    def _on_direct(self, switch, _param) -> None:
        if self._syncing:
            return
        self.cfg["direct"] = switch.get_active()
        save_config(self.cfg)
        self._refresh_direct_note()


    def _on_keep(self, switch, _param) -> None:
        if self._syncing:
            return
        self.cfg["keep_streaming"] = switch.get_active()
        save_config(self.cfg)


    def _on_autonext(self, switch, _param) -> None:
        self.cfg["autonext"] = switch.get_active()
        save_config(self.cfg)


    def _adopt_session(self) -> bool:
        state = streamer.load_session()
        if state is None:
            return False
        session = streamer.Session()
        session.restore(state)
        # Match saved receiver.
        if state.device != self._device():
            return False
        # Check HLS/server ownership off-thread.
        if not session.active() and session.mode != "transcode":
            streamer.clear_session()
            return False
        # Verify stream identity before exposing controls.
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
                # Retain state on an unreachable receiver; clear only known mismatches.
                if info is not None:
                    streamer.clear_session()
                self.toast("Previous cast could not be verified")
                self._refresh_controls()
                self._poll_device()
                return
            # Expose controls only after receiver identity is confirmed.
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
                chain, hint = streamer.monitor_summary(
                    state.audio, gain, streamer.state_loudness(state))
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

        Async.run(probe, done=probed, failed=failed, domain="status")
        self._refresh_controls()
        self._poll_device()
        return False






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
        # Observe before the tracker is cleared; never alters the failure path.
        self._recovery_plan = cast_recovery.plan_for_window(self, message)
        try:  # remember this failed (receiver, mode) so the planner never re-offers it
            self._cast_tried = [*getattr(self, "_cast_tried", [])[-15:],
                                (self._device(), getattr(self, "_attempt_mode", "direct"))]
        except Exception:  # noqa: BLE001 - bookkeeping must never break failure handling
            self._cast_tried = list(getattr(self, "_cast_tried", []))  # keep prior attempts
        self._dlna_cancel = None
        reliability_metrics.fail_attempt(self, Async.run)
        reliability_metrics.finish_active(self, "failed", Async.run)
        self.busy = False
        self._stop_monitor()
        self._set_levels_hint("")
        if self.session is not None and not self.session.active():
            self.session = None
        if self.session is None:
            self.tracker.clear()
            self._finished_handled = False
        retry = self._retry_action()
        option = self._recovery_plan.primary if retry and self._recovery_plan else None
        why = f" — {option.reason}" if option is not None and option.kind != "retry" else ""
        self.toast(f"Cast failed: {message}{why}", error=True, **({"action": retry} if retry else {}))
        self._console(f"Cast failed [{cast_failure_code.note(message)}]: {message}")
        if self._recovery_plan is not None:
            self._console(cast_recovery.summary_line(self._recovery_plan))
        self._notify("error", message)
        self._refresh_controls()


    def _skip(self, delta: float) -> None:
        preview = (self.session is None and self._preview_path is not None
                   and not self.external)
        position = self._preview_position if preview else self.tracker.value()
        if position is None:
            self.toast("Position unknown — nothing to skip in")
            return
        self.seek_to(position + delta)
