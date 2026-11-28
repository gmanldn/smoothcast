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


class DeviceDiscoveryMixin:
    def scan_devices(self) -> None:
        if self.scan_busy:
            # Queue one refresh, rather than publishing the older in-flight
            # result or launching unbounded simultaneous SSDP scans.
            self._scan_again = True
            return
        self._scan_again = False
        self.scan_busy = True
        self.device_detail.set_text("Scanning Cast and DLNA receivers…")

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
            if self._closing:
                self.scan_busy = False
                return
            if self._scan_again:
                self.scan_busy = False
                self.scan_devices()
                return
            self._scan_done(devices)

        def failed(message):
            if self._closing:
                self.scan_busy = False
                return
            if self._scan_again:
                self.scan_busy = False
                self.scan_devices()
                return
            self._scan_failed(message)

        Async.run(work, done=completed, failed=failed, domain="discovery")

    def _initial_scan(self) -> bool:
        self.scan_devices()
        return False

    def _scan_done(self, devices) -> None:
        self.scan_busy = False
        cast_fresh = dlna_fresh = True
        if isinstance(devices, tuple):
            cast_devices, discovered_dlna = devices
            cast_fresh = cast_devices is not None
            dlna_fresh = discovered_dlna is not None
            if cast_devices is None:
                cast_devices = self.devices
            if discovered_dlna is not None:
                self.dlna_devices = discovered_dlna
        else:
            cast_devices = devices
        self.devices = cast_devices
        self._dlna_by_key = {renderer.key: renderer for renderer in self.dlna_devices}
        saved_uuid = self.cfg.get("device_uuid", "")
        unlocked = not (self.session is not None or self.busy
                        or self._cast_starting or self.external)
        if unlocked and saved_uuid and cast_fresh:
            matched = castctl.uniquely_named_device(saved_uuid, cast_devices)
            if matched is not None and matched.name != self.cfg["device"]:
                # Pending volume write targets the old receiver.
                if self._volume_job is not None:
                    GLib.source_remove(self._volume_job)
                    self._volume_job = None
                self._volume_target = None
                self.cfg["device"] = matched.name
                save_config(self.cfg)
                self.toast(f"Reconnected renamed Cast receiver: {matched.name}")
                self._poll_device()
        names = cast_targets.ordered_names(
            [d.name for d in cast_devices] + list(self._dlna_by_key),
            self.cfg.get("cast_targets", []),
            self.cfg.get("device_favourites", []),
            self.cfg.get("device_last_used"),
        )
        selected = cast_targets.select_index(names, self.cfg["device"])
        self._syncing = True
        self.device_dropdown.set_model(Gtk.StringList.new(names))
        self.device_dropdown.set_selected(selected)
        self._syncing = False
        selected = next((d for d in cast_devices if d.name == self.cfg["device"]), None)
        # Migrate older configurations when the selected display name itself
        # is unique. Do not adopt a duplicate name or overwrite a saved UUID.
        if cast_fresh and not saved_uuid and selected is not None and selected.uuid:
            unique = castctl.uniquely_named_device(selected.uuid, cast_devices)
            if unique is selected:
                self.cfg["device_uuid"] = selected.uuid
                save_config(self.cfg)
        dlna_selected = self._dlna_renderer()
        if ((self._device().startswith("DLNA · ") and not dlna_fresh)
                or (not self._device().startswith("DLNA · ") and not cast_fresh)):
            self.device_detail.set_text("Discovery incomplete — checking the selected receiver")
            self._set_device_badge("CHECKING")
        elif dlna_selected is not None:
            self.device_detail.set_text(
                f"DLNA/UPnP · {dlna_selected.model or 'MediaRenderer'} · {dlna_selected.host}"
            )
            self._set_device_badge("DLNA FOUND")
        elif selected is not None:
            self.device_detail.set_text(
                f"{selected.model or 'Google Cast receiver'} · {selected.manufacturer or 'Unknown maker'} · {selected.host}"
            )
            self._set_device_badge("FOUND ON LAN")
        elif self.cfg["device"] in self.cfg.get("cast_targets", []):
            self.device_detail.set_text(
                f"Manual Google Cast target {self.cfg['device']} · checking connectivity"
            )
            self._set_device_badge("MANUAL IP")
        else:
            self.device_detail.set_text(
                "Selected Cast receiver not found. Choose another receiver or add its IP."
                if cast_devices or self.dlna_devices else "No Cast or DLNA receivers discovered. Check Wi-Fi/VPN or firewall."
            )
            self._set_device_badge("NOT FOUND", "offline")
        if self._device() and self.device_state in {"OFFLINE", "UNKNOWN"}:
            self._poll_device()
        if hasattr(self, "_refresh_network_activity"):
            self._refresh_network_activity()

    def _scan_failed(self, message) -> None:
        self.scan_busy = False
        # A failed scan is not a successful empty scan. Retain the last known
        # targets and let the independent status query determine reachability.
        self.device_detail.set_text("Scan failed — last known targets retained; check Wi-Fi or VPN")
        self._set_device_badge("SCAN FAILED", "offline")
        self.toast(str(message), error=True)

    def _poll_device(self) -> bool:
        device = self._device()
        renderer = self._dlna_renderer(device)
        if castctl.watch_status(self, device, renderer is None,
                                GLib.idle_add, self._poll_done):
            return True
        if self.poll_busy:
            return True
        if device.startswith("DLNA · ") and renderer is None:
            # A missing DLNA discovery record must never be sent to catt.
            self._poll_done(None)
            return True
        self.poll_busy = True

        def completed(info):
            # A late response belongs only to the receiver it queried.
            if device != self._device():
                self.poll_busy = False
                self._poll_device()
                return
            self._poll_done(info)

        def failed(message):
            if device != self._device():
                self.poll_busy = False
                self._poll_device()
                return
            self._poll_failed(message)

        Async.run(
            (lambda: dlna.info(renderer)) if renderer else (lambda: castctl.info(device)),
            done=completed, failed=failed, domain="status",
        )
        return True

    def _poll_done(self, info) -> None:
        self.poll_busy = False
        # A busy receiver often misses one status read; keep the last good
        # reading for two misses instead of flashing the device "Offline".
        if info is None and self.device_info is not None and getattr(self, "_poll_misses", 0) < 2:
            self._poll_misses = getattr(self, "_poll_misses", 0) + 1
            return
        self._poll_misses = 0
        previous = self.device_state
        self.device_info = info
        self.device_state = castctl.player_state(info)
        if info is None:
            self.device_state = "OFFLINE"
        self._set_device_badge(
            state_labels.present(self.device_state).short.upper(),
            "offline" if self.device_state == "OFFLINE" else "online",
        )
        reliability_metrics.observe(self, self.device_state)
        self.tracker.set_state(self.device_state in {"PLAYING", "BUFFERING"})
        if self.session and info:
            # Chromecast reports the *new HLS playlist's* current_time from
            # zero after each seek. Convert it to source-file seconds, including
            # the original -ss offset and any non-1× playback rate. Direct play
            # already uses the source timeline and needs no conversion.
            current_time = info.get("current_time")
            duration = info.get("duration")
            if current_time is not None:
                try:
                    device_time = float(current_time)
                    state = self.session.state
                    if self.session.mode == "transcode" and state is not None:
                        absolute = playback_state.absolute_encoded_position(
                            state.offset, device_time, state.duration,
                            speed=state.speed,
                        )
                        if absolute is not None:
                            self.tracker.device_update(
                                absolute, state.duration, rate=state.speed,
                            )
                    else:
                        self.tracker.device_update(
                            device_time, float(duration) if duration else None,
                            rate=1.0,
                        )
                except (TypeError, ValueError, OverflowError):
                    pass
        volume = castctl.volume_percent(info)
        if volume is not None and time.monotonic() - self._volume_user_ts > 3:
            self._syncing = True
            self.volume_scale.set_value(volume)
            self._syncing = False
        if info is not None:
            muted = castctl.volume_muted(info)
            self._syncing = True
            self.mute_button.set_active(muted)
            self._syncing = False
            self._apply_volume_icon()
        self._detect_external()
        if self.external and info:
            title, _size = playback_state.external_media_labels(info)
            details = playback_state.external_details(info)
            if self.np_title.get_text() != title:
                self.np_title.set_text(title)
            if details and self.np_meta.get_text() != details:
                self.np_meta.set_text(details)
        if self.session is None and self._url_cast_url is not None:
            if playback_state.url_cast_matches(info, self._url_cast_url):
                self._url_cast_seen = True
            elif self._url_cast_seen:
                # A different active content replaced our URL cast; never stop
                # that replacement when the sleep timer expires.
                self._url_cast_url = None
                self._url_cast_seen = False
        if playback_state.playback_ended(
            previous, self.device_state,
            has_session=self.session is not None, busy=self.busy,
        ):
            self._maybe_finished()
        self._join_slate_observe(info)
        self._refresh_controls()
        self._update_header_subtitle()

    def _poll_failed(self, message) -> None:
        self.poll_busy = False
        self.device_info = None
        self.device_state = "OFFLINE"
        clock = getattr(self, "_external_display_clock", None)
        if clock is not None:
            clock.set_state(False)
        self._set_device_badge("OFFLINE", "offline")
        self._refresh_controls()
        self._console(f"Device status unavailable: {message}")

    def _add_cast_target(self) -> None:
        """Manually connect to a Google Cast receiver when mDNS is blocked."""
        # Return and Add IP reach this handler even when a widget is disabled
        # (for instance, a pending signal). Never retarget an owned TV.
        if (self.session is not None or self.busy
                or self._cast_starting or self.external):
            self.toast("Stop this cast before switching receivers.", error=True)
            return
        try:
            target = castctl.validate_manual_target(self.cast_ip_entry.get_text())
        except ValueError:
            self.toast("Enter a valid private IPv4 address for a Google Cast receiver.", error=True)
            return
        targets = self.cfg.get("cast_targets")
        if not isinstance(targets, list):
            targets = []
        if target not in targets:
            targets.append(target)
        self.cfg["cast_targets"] = targets[-32:]
        self.cfg["device"] = target
        self.cfg["device_uuid"] = ""  # Manual IP does not claim a discovered identity.
        save_config(self.cfg)
        self.cast_ip_entry.set_text("")
        self._scan_done(self.devices)
        self.toast(f"Added Google Cast target {target}; checking receiver")
        self._poll_device()

    def _on_device_selected(self, dropdown, _param) -> None:
        if self._syncing:
            return
        index = dropdown.get_selected()
        model = dropdown.get_model()
        if index == Gtk.INVALID_LIST_POSITION or model is None:
            return
        name = model.get_string(index)
        if name == cast_targets.CHOOSE_RECEIVER:
            return
        if (name and name != self.cfg["device"]
                and (self.session is not None or self.busy
                     or self._cast_starting or self.external)):
            # Keep A selected even if a queued GTK signal tries to select B.
            # Commands already in flight must retain their receiver identity.
            self._syncing = True
            try:
                for current_index in range(model.get_n_items()):
                    if model.get_string(current_index) == self.cfg["device"]:
                        dropdown.set_selected(current_index)
                        break
            finally:
                self._syncing = False
            self.toast("Stop this cast before switching receivers.", error=True)
            return
        if name and name != self.cfg["device"]:
            # Never allow a previously queued volume write for A to affect B.
            if self._volume_job is not None:
                GLib.source_remove(self._volume_job)
                self._volume_job = None
            self._volume_target = None
            self.cfg["device"] = name
            matches = [d for d in self.devices if d.name == name and d.uuid]
            self.cfg["device_uuid"] = (
                matches[0].uuid if name not in self._dlna_by_key
                and name not in self.cfg.get("cast_targets", [])
                and len(matches) == 1
                and castctl.uniquely_named_device(matches[0].uuid, self.devices)
                    is matches[0] else ""
            )
            save_config(self.cfg)
            self.title_widget.set_subtitle(name)
            self.toast(f"Now controlling {name}")
            self._set_device_badge("CONNECTING")
            self._poll_device()

    def _detect_external(self) -> None:
        info = self.device_info
        idle = (self.device_state in {"OFFLINE", "IDLE", "UNKNOWN"}
                or self._join_slate_showing(info))  # our own idle slate is not user playback (#420)
        if idle:
            self._external_runtime = None
            self._external_display_clock = None
            if self.external:
                self.external = False
            # An idle receiver must not leave an old URL cast marked as owned.
            self._url_cast_url = None
            self._url_cast_seen = False
            if not self.session:
                self.now_playing = None
                self.tracker.clear()
            return
        state = self.session.state if self.session is not None else None
        if state is not None:
            if (state.mode == "transcode" and
                    playback_state.hls_session_matches(
                        info, state.stream_url, state.title,
                    )):
                self.external = False  # Exact saved HLS URL; encoder may be done.
                return
            if (state.mode == "direct" and
                    playback_state.direct_session_matches(info, state.title)):
                self.external = False
                return
            if state.mode not in {"transcode", "direct"} and self.session.active():
                self.external = False
                return
        # A matching port, title or playlist suffix is NOT ownership proof.
        # Without a matching saved stream the receiver is playing other media.
        self.external = True
        self.tracker.clear()
        self._external_runtime = None
        clock = playback_state.external_display_clock(info, self.device_state)
        self._external_display_clock = clock
        # Paint the first receiver sample immediately, including paused media.
        # The separate display clock never makes the external stream seekable.
        if hasattr(self, "np_title"):
            title, size = playback_state.external_media_labels(info)
            self.np_title.set_text(title)
            self.np_title.set_tooltip_text(title)
            length = fmt_time(clock.duration) if clock.duration else "not reported by the source"
            self.np_meta.set_text(f"{size} · Length: {length} · External stream")
        if hasattr(self, "seekbar"):
            position = clock.value()
            self.seekbar.set_state(position, clock.duration, None, unknown_length=position is not None)
            if not getattr(self.seekbar, "scrubbing", False):
                self.elapsed_label.set_text(fmt_time(position))
                self.remaining_label.set_text(playback_state.external_length_label(info))

    def _device(self) -> str:
        return self.cfg["device"]

    def _dlna_renderer(self, device: str | None = None) -> dlna.Renderer | None:
        return self._dlna_by_key.get(device or self._device())

    def _volume_control_available(self) -> bool:
        return not self._device().startswith("DLNA · ") or getattr(
            self._dlna_renderer(), "supports_rendering_control", False
        )

    def _device_host(self, device: str) -> str | None:
        renderer = self._dlna_renderer(device)
        if renderer is not None:
            return renderer.host
        if device in self.cfg.get("cast_targets", []):
            return device
        return castctl.unique_discovered_host(device, self.devices)
