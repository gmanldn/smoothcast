"""Receiver discovery, status polling and selection for the main window."""
from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib, Gtk
import time
from concurrent.futures import ThreadPoolExecutor
import castctl
import state_labels
import dlna
import playback_state
import cast_targets
import reliability_metrics
import errors
from async_jobs import UserFacingError
from cast_widgets import save_config, fmt_time, Async


class DeviceDiscoveryController:
    """Composition replacement for DeviceDiscoveryMixin (#691); all state stays on the window."""

    def __init__(self, window) -> None:
        self.w = window

    def scan_devices(self) -> None:
        w = self.w
        if w.scan_busy:
            # Queue one refresh, rather than publishing the older in-flight
            # result or launching unbounded simultaneous SSDP scans.
            w._scan_again = True
            return
        w._scan_again = False
        w.scan_busy = True
        w.device_detail.set_text("Scanning Cast and DLNA receivers…")

        def work():
            failures = []
            # These are independent network protocols. Start both while this
            # bounded discovery worker is active, then merge only their
            # results here; GTK state remains owned by the completion callback.
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="receiver-discovery") as pool:
                cast_future = pool.submit(castctl.scan)
                dlna_future = pool.submit(dlna.discover)
                try:
                    cast_devices = cast_future.result()
                except Exception as exc:
                    cast_devices = None
                    failures.append(f"Cast discovery: {exc}")
                    errors.record("discovery.failed", {"protocol": "cast"})
                try:
                    dlna_devices = dlna_future.result()
                except Exception as exc:
                    dlna_devices = None
                    failures.append(f"DLNA discovery: {exc}")
                    errors.record("discovery.failed", {"protocol": "dlna"})
            if cast_devices is None and dlna_devices is None:
                spec = errors.CATALOGUE["discovery.failed"]
                raise UserFacingError(
                    spec.message, detail="; ".join(failures), code=spec.code,
                )
            return cast_devices, dlna_devices

        def completed(devices):
            if w._closing:
                w.scan_busy = False
                return
            if w._scan_again:
                w.scan_busy = False
                # Publish the completed snapshot before servicing the queued
                # refresh, so a discovered receiver is never hidden behind
                # successive scan requests.
                w._scan_done(devices)
                w.scan_devices()
                return
            w._scan_done(devices)

        def failed(message):
            if w._closing:
                w.scan_busy = False
                return
            if w._scan_again:
                w.scan_busy = False
                w.scan_devices()
                return
            w._scan_failed(message)

        Async.run(work, done=completed, failed=failed, domain="discovery")

    def _initial_scan(self) -> bool:
        w = self.w
        w.scan_devices()
        return False

    def _scan_done(self, devices) -> None:
        w = self.w
        w.scan_busy = False
        cast_fresh = dlna_fresh = True
        if isinstance(devices, tuple):
            cast_devices, discovered_dlna = devices
            cast_fresh = cast_devices is not None
            dlna_fresh = discovered_dlna is not None
            if cast_devices is None:
                cast_devices = w.devices
            if discovered_dlna is not None:
                w.dlna_devices = discovered_dlna
        else:
            cast_devices = devices
        w.devices = cast_devices
        w._dlna_by_key = {renderer.key: renderer for renderer in w.dlna_devices}
        saved_uuid = w.cfg.get("device_uuid", "")
        unlocked = not (w.session is not None or w.busy
                        or w._cast_starting or w.external)
        if unlocked and saved_uuid and cast_fresh:
            matched = castctl.uniquely_named_device(saved_uuid, cast_devices)
            if matched is not None and matched.name != w.cfg["device"]:
                # Pending volume write targets the old receiver.
                if w._volume_job is not None:
                    GLib.source_remove(w._volume_job)
                    w._volume_job = None
                w._volume_target = None
                w.cfg["device"] = matched.name
                save_config(w.cfg)
                w.toast(f"Reconnected renamed Cast receiver: {matched.name}")
                w._poll_device()
        names = cast_targets.ordered_names(
            [d.name for d in cast_devices] + list(w._dlna_by_key),
            w.cfg.get("cast_targets", []),
            w.cfg.get("device_favourites", []),
            w.cfg.get("device_last_used"),
        )
        selected = cast_targets.select_index(names, w.cfg["device"])
        model = w.device_dropdown.get_model()
        same_names = (model is not None and model.get_n_items() == len(names)
                      and all(model.get_string(i) == name for i, name in enumerate(names)))
        if not same_names or w.device_dropdown.get_selected() != selected:
            w._syncing = True
            try:
                if not same_names:
                    w.device_dropdown.set_model(Gtk.StringList.new(names))
                if w.device_dropdown.get_selected() != selected:
                    w.device_dropdown.set_selected(selected)
            finally:
                w._syncing = False
        selected = next((d for d in cast_devices if d.name == w.cfg["device"]), None)
        # Migrate older configurations when the selected display name itself
        # is unique. Do not adopt a duplicate name or overwrite a saved UUID.
        if cast_fresh and not saved_uuid and selected is not None and selected.uuid:
            unique = castctl.uniquely_named_device(selected.uuid, cast_devices)
            if unique is selected:
                w.cfg["device_uuid"] = selected.uuid
                save_config(w.cfg)
        dlna_selected = w._dlna_renderer()
        if ((w._device().startswith("DLNA · ") and not dlna_fresh)
                or (not w._device().startswith("DLNA · ") and not cast_fresh)):
            w.device_detail.set_text("Discovery incomplete — checking the selected receiver")
            w._set_device_badge("CHECKING")
        elif dlna_selected is not None:
            w.device_detail.set_text(
                f"DLNA/UPnP · {dlna_selected.model or 'MediaRenderer'} · {dlna_selected.host}"
            )
            w._set_device_badge("DLNA FOUND")
        elif selected is not None:
            w.device_detail.set_text(
                f"{selected.model or 'Google Cast receiver'} · {selected.manufacturer or 'Unknown maker'} · {selected.host}"
            )
            w._set_device_badge("FOUND ON LAN")
        elif w.cfg["device"] in w.cfg.get("cast_targets", []):
            w.device_detail.set_text(
                f"Manual Google Cast target {w.cfg['device']} · checking connectivity"
            )
            w._set_device_badge("MANUAL IP")
        else:
            w.device_detail.set_text(
                "Selected Cast receiver not found. Choose another receiver or add its IP."
                if cast_devices or w.dlna_devices else "No Cast or DLNA receivers discovered. Check Wi-Fi/VPN or firewall."
            )
            w._set_device_badge("NOT FOUND", "offline")
        if w._device() and w.device_state in {"OFFLINE", "UNKNOWN"}:
            w._poll_device()
        if hasattr(w, "_refresh_network_activity"):
            w._refresh_network_activity()

    def _scan_failed(self, message) -> None:
        w = self.w
        w.scan_busy = False
        # A failed scan is not a successful empty scan. Retain the last known
        # targets and let the independent status query determine reachability.
        w.device_detail.set_text("Scan failed — last known targets retained; check Wi-Fi or VPN")
        w._set_device_badge("SCAN FAILED", "offline")
        w.toast(str(message), error=True)

    def _poll_device(self) -> bool:
        w = self.w
        device = w._device()
        renderer = w._dlna_renderer(device)
        if castctl.watch_status(w, device, renderer is None,
                                GLib.idle_add, w._poll_done):
            return True
        if w.poll_busy:
            return True
        if device.startswith("DLNA · ") and renderer is None:
            # A missing DLNA discovery record must never be sent to catt.
            w._poll_done(None)
            return True
        w.poll_busy = True

        def completed(info):
            # A late response belongs only to the receiver it queried.
            if device != w._device():
                w.poll_busy = False
                w._poll_device()
                return
            w._poll_done(info)

        def failed(message):
            if device != w._device():
                w.poll_busy = False
                w._poll_device()
                return
            w._poll_failed(message)

        Async.run(
            (lambda: dlna.info(renderer)) if renderer else (lambda: castctl.info(device)),
            done=completed, failed=failed, domain="status",
        )
        return True

    def _poll_done(self, info) -> None:
        w = self.w
        w.poll_busy = False
        # A busy receiver often misses one status read; keep the last good
        # reading for two misses instead of flashing the device "Offline".
        if info is None and w.device_info is not None and getattr(w, "_poll_misses", 0) < 2:
            w._poll_misses = getattr(w, "_poll_misses", 0) + 1
            return
        w._poll_misses = 0
        previous = w.device_state
        w.device_info = info
        w.device_state = castctl.player_state(info)
        if info is None:
            w.device_state = "OFFLINE"
        w._set_device_badge(
            state_labels.present(w.device_state).short.upper(),
            "offline" if w.device_state == "OFFLINE" else "online",
        )
        reliability_metrics.observe(w, w.device_state)
        w.tracker.set_state(w.device_state in {"PLAYING", "BUFFERING"})
        if w.session and info:
            # Chromecast reports the *new HLS playlist's* current_time from
            # zero after each seek. Convert it to source-file seconds, including
            # the original -ss offset and any non-1× playback rate. Direct play
            # already uses the source timeline and needs no conversion.
            current_time = info.get("current_time")
            duration = info.get("duration")
            if current_time is not None:
                try:
                    device_time = float(current_time)
                    state = w.session.state
                    if w.session.mode == "transcode" and state is not None:
                        absolute = playback_state.absolute_encoded_position(
                            state.offset, device_time, state.duration,
                            speed=state.speed,
                        )
                        if absolute is not None:
                            w.tracker.device_update(
                                absolute, state.duration, rate=state.speed,
                            )
                    else:
                        w.tracker.device_update(
                            device_time, float(duration) if duration else None,
                            rate=1.0,
                        )
                except (TypeError, ValueError, OverflowError):
                    pass
        volume = castctl.volume_percent(info)
        if volume is not None and time.monotonic() - w._volume_user_ts > 3:
            w._syncing = True
            w.volume_scale.set_value(volume)
            w._syncing = False
        if info is not None:
            muted = castctl.volume_muted(info)
            w._syncing = True
            w.mute_button.set_active(muted)
            w._syncing = False
            w._apply_volume_icon()
        w._detect_external()
        if w.external and info:
            title, _size = playback_state.external_media_labels(info)
            details = playback_state.external_details(info)
            if w.np_title.get_text() != title:
                w.np_title.set_text(title)
            if details and w.np_meta.get_text() != details:
                w.np_meta.set_text(details)
        if w.session is None and w._url_cast_url is not None:
            if playback_state.url_cast_matches(info, w._url_cast_url):
                w._url_cast_seen = True
            elif w._url_cast_seen:
                # A different active content replaced our URL cast; never stop
                # that replacement when the sleep timer expires.
                w._url_cast_url = None
                w._url_cast_seen = False
        if playback_state.playback_ended(
            previous, w.device_state,
            has_session=w.session is not None, busy=w.busy,
        ):
            w._maybe_finished()
        w._join_slate_observe(info)
        w._refresh_controls()
        w._update_header_subtitle()

    def _poll_failed(self, message) -> None:
        w = self.w
        w.poll_busy = False
        w.device_info = None
        w.device_state = "OFFLINE"
        clock = getattr(w, "_external_display_clock", None)
        if clock is not None:
            clock.set_state(False)
        w._set_device_badge("OFFLINE", "offline")
        w._refresh_controls()
        w._console(f"Device status unavailable: {message}")

    def _add_cast_target(self) -> None:
        """Manually connect to a Google Cast receiver when mDNS is blocked."""
        w = self.w
        # Return and Add IP reach this handler even when a widget is disabled
        # (for instance, a pending signal). Never retarget an owned TV.
        if (w.session is not None or w.busy
                or w._cast_starting or w.external):
            w.toast("Stop this cast before switching receivers.", error=True)
            return
        try:
            target = castctl.validate_manual_target(w.cast_ip_entry.get_text())
        except ValueError:
            w.toast("Enter a valid private IPv4 address for a Google Cast receiver.", error=True)
            return
        targets = w.cfg.get("cast_targets")
        if not isinstance(targets, list):
            targets = []
        if target not in targets:
            targets.append(target)
        w.cfg["cast_targets"] = targets[-32:]
        w.cfg["device"] = target
        w.cfg["device_uuid"] = ""  # Manual IP does not claim a discovered identity.
        save_config(w.cfg)
        w.cast_ip_entry.set_text("")
        w._scan_done(w.devices)
        w.toast(f"Added Google Cast target {target}; checking receiver")
        w._poll_device()

    def _on_device_selected(self, dropdown, _param) -> None:
        w = self.w
        if w._syncing:
            return
        index = dropdown.get_selected()
        model = dropdown.get_model()
        if index == Gtk.INVALID_LIST_POSITION or model is None:
            return
        name = model.get_string(index)
        if name == cast_targets.CHOOSE_RECEIVER:
            return
        if (name and name != w.cfg["device"]
                and (w.session is not None or w.busy
                     or w._cast_starting or w.external)):
            # Keep A selected even if a queued GTK signal tries to select B.
            # Commands already in flight must retain their receiver identity.
            w._syncing = True
            try:
                for current_index in range(model.get_n_items()):
                    if model.get_string(current_index) == w.cfg["device"]:
                        dropdown.set_selected(current_index)
                        break
            finally:
                w._syncing = False
            w.toast("Stop this cast before switching receivers.", error=True)
            return
        if name and name != w.cfg["device"]:
            # Never allow a previously queued volume write for A to affect B.
            if w._volume_job is not None:
                GLib.source_remove(w._volume_job)
                w._volume_job = None
            w._volume_target = None
            w.cfg["device"] = name
            matches = [d for d in w.devices if d.name == name and d.uuid]
            w.cfg["device_uuid"] = (
                matches[0].uuid if name not in w._dlna_by_key
                and name not in w.cfg.get("cast_targets", [])
                and len(matches) == 1
                and castctl.uniquely_named_device(matches[0].uuid, w.devices)
                    is matches[0] else ""
            )
            save_config(w.cfg)
            w.title_widget.set_subtitle(name)
            w.toast(f"Now controlling {name}")
            w._set_device_badge("CONNECTING")
            w._poll_device()

    def _detect_external(self) -> None:
        w = self.w
        info = w.device_info
        idle = (w.device_state in {"OFFLINE", "IDLE", "UNKNOWN"}
                or w._join_slate_showing(info))  # our own idle slate is not user playback (#420)
        if idle:
            w._external_runtime = None
            w._external_display_clock = None
            if w.external:
                w.external = False
            # An idle receiver must not leave an old URL cast marked as owned.
            w._url_cast_url = None
            w._url_cast_seen = False
            if not w.session:
                w.now_playing = None
                w.tracker.clear()
            return
        state = w.session.state if w.session is not None else None
        if state is not None:
            if (state.mode == "transcode" and
                    playback_state.hls_session_matches(
                        info, state.stream_url, state.title,
                    )):
                w.external = False  # Exact saved HLS URL; encoder may be done.
                return
            if (state.mode == "direct" and
                    playback_state.direct_session_matches(info, state.title)):
                w.external = False
                return
            if state.mode not in {"transcode", "direct"} and w.session.active():
                w.external = False
                return
        # A matching port, title or playlist suffix is NOT ownership proof.
        # Without a matching saved stream the receiver is playing other media.
        w.external = True
        w.tracker.clear()
        w._external_runtime = None
        clock = playback_state.external_display_clock(info, w.device_state)
        w._external_display_clock = clock
        # Paint the first receiver sample immediately, including paused media.
        # The separate display clock never makes the external stream seekable.
        if hasattr(w, "np_title"):
            title, size = playback_state.external_media_labels(info)
            w.np_title.set_text(title)
            w.np_title.set_tooltip_text(title)
            length = fmt_time(clock.duration) if clock.duration else "not reported by the source"
            w.np_meta.set_text(f"{size} · Length: {length} · External stream")
        if hasattr(w, "seekbar"):
            position = clock.value()
            w.seekbar.set_state(position, clock.duration, None, unknown_length=position is not None)
            if not getattr(w.seekbar, "scrubbing", False):
                w.elapsed_label.set_text(fmt_time(position))
                w.remaining_label.set_text(playback_state.external_length_label(info))

    def _device(self) -> str:
        w = self.w
        return w.cfg["device"]

    def _dlna_renderer(self, device: str | None = None) -> dlna.Renderer | None:
        w = self.w
        return w._dlna_by_key.get(device or w._device())

    def _volume_control_available(self) -> bool:
        w = self.w
        return not w._device().startswith("DLNA · ") or getattr(
            w._dlna_renderer(), "supports_rendering_control", False
        )

    def _device_host(self, device: str) -> str | None:
        w = self.w
        renderer = w._dlna_renderer(device)
        if renderer is not None:
            return renderer.host
        if device in w.cfg.get("cast_targets", []):
            return device
        return castctl.unique_discovered_host(device, w.devices)

    @classmethod
    def install(cls, window) -> "DeviceDiscoveryController":
        """Bind every method onto ``window`` and return the controller."""
        controller = cls(window)
        for name in DEVICE_DISCOVERY_CONTROLLER_METHODS:
            setattr(window, name, getattr(controller, name))
        return controller


DEVICE_DISCOVERY_CONTROLLER_METHODS = ('scan_devices', '_initial_scan', '_scan_done', '_scan_failed', '_poll_device', '_poll_done', '_poll_failed', '_add_cast_target', '_on_device_selected', '_detect_external', '_device', '_dlna_renderer', '_volume_control_available', '_device_host')
