#!/usr/bin/env python3
"""Shared SmoothCast constants, config helpers and custom GTK widgets."""
from __future__ import annotations
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


from gi.repository import GLib, Gtk
import pathlib
import threading
import castctl
import config_control
import config_persistence
import idle_chrome

import audio_monitor
import ui_theme
import error_log
import async_jobs


APP_ID = "local.cast-control"
APP_NAME = "SmoothCast"
CONFIG_DIR = pathlib.Path(GLib.get_user_config_dir()) / "cast-control"
CONFIG_FILE = CONFIG_DIR / "config.json"
ROOM_CHECKPOINT_FILE = CONFIG_DIR / "room-checkpoint.json"
ICON_NAME = APP_ID
DEFAULTS: dict = {
    "schema_version": 1,  # == config_control.SCHEMA_VERSION (tested).
    "device": castctl.DEFAULT_DEVICE,
    "device_uuid": "",  # Stable Cast identity; manual/DLNA: name-based.
    "cast_targets": [],
    "device_favourites": [],
    "device_last_used": {},
    "quality": "balanced",
    "audio": "dialogue",
    "audio_gain": 6.0,
    "audio_loudness": "off",  # EBU R128 programme/album (#139)
    "music_autogain": False,
    "subs": "auto",
    "subs_path": "",
    "subtitle_track_by_file": {},
    "subtitle_delay_by_file": {},
    "audio_delay_by_file": {},  # per-film lip-sync delay in ms, +/-5000 (#113)
    "subtitle_style": "default",  # burned-in caption preset, see subtitle_style.py (#34)
    "audio_track_by_file": {},
    "burn_subs": False,
    "direct": True,
    "autonext": False,
    "auto_shutdown": False,
    "notifications": True,  # Notify when the window is unfocused (#267)
    "portal_screens": True,
    "house_pin_enabled": False,
    "library_indexer": True,
    "library_folders": [],
    "keep_streaming": True,
    "color_scheme": "prefer-dark",
    "accent": "default",  # Accent preset; "default" = no override (#135).
    "density": "comfortable",  # compact | comfortable | spacious (#136).
    "auto_theme": False,
    "recents": [],
    "favourites": [],
    "watch_history": [],
    "bookmarks": [],
    "positions": {},
    "loop": False,
    "loop_all": False,
    "shuffle_seed": 1,
    "playback_speed": 1.0,
    "rotation": 0,
    "sleep_timer_minutes": 0,
    "sleep_timer_deadline": 0.0,
    "sleep_fade_seconds": 30,  # Fade volume out this long before the sleep timer stops; 0 = off (#270).
    "window_width": 1600,
    "window_height": 1000,
    "window_x": -1,
    "window_y": -1,
    "auto_update": True,  # Startup git pull of a release checkout (#230).
    "verify_updates": False,  # Require a GPG-verified commit or tag to update.
    "hls_port": 8767,  # Preferred HLS port; a free one is used if taken (#231).
    "portal_port": 0,  # Choose one random high room port and persist it (#456).
    "lower_ffmpeg_priority": True,  # Run FFmpeg at below-normal priority (#247).
    "preferred_audio_languages": [],  # e.g. ["ja", "en"]; empty = file default (#38)
    "preferred_subtitle_languages": [],  # e.g. ["en"]; empty = previous behaviour (#38)
    "language_overrides": {},  # {"series name": {"audio": [...], "subtitles": [...]}} (#38)
    "auto_crop": False,  # Detect and crop black bars before casting (#54).
    "auto_deinterlace": False,  # Deinterlace only when the film is clearly interlaced (#54).
    "cache_cap_mb": 8192,  # Scratch cap per DLNA conversion; 0 = unlimited (#277).
}


CSS = ui_theme.CSS


def load_config() -> dict:
    return config_control.load_file(CONFIG_FILE, DEFAULTS)


config_persistence.configure(CONFIG_FILE, DEFAULTS, error_log.log)
save_config = config_persistence.save_config
refresh_config = config_persistence.refresh_config
flush_config = config_persistence.flush_config


def fmt_time(seconds: float | None) -> str:
    return castctl.fmt_time(seconds)


class Async:
    """GTK-facing adapter for bounded, domain-specific background work."""

    _domains: async_jobs.WorkDomains | None = None
    _lock = threading.Lock()

    @classmethod
    def run(cls, work, done=None, failed=None, *, domain="background", valid=None):
        # The singleton is lazy: importing widgets or running a GUI smoke test
        # neither starts network I/O nor creates background threads.
        with cls._lock:
            if cls._domains is None:
                cls._domains = async_jobs.WorkDomains(
                    GLib.idle_add, on_error=error_log.log,
                )
            domains = cls._domains
        return domains.submit(
            work, done=done, failed=failed, domain=domain, valid=valid,
        )

    @classmethod
    def shutdown(cls):
        """Cancel pending jobs and suppress late GTK callbacks on app exit."""
        with cls._lock:
            domains = cls._domains
        if domains is not None:
            domains.shutdown()


class SeekBar(Gtk.DrawingArea):
    def __init__(self, on_seek, on_hover) -> None:
        super().__init__()
        self.position = 0.0
        self.duration = 0.0
        self.buffered = 0.0
        self.scrubbing = False
        self.scrub_value = 0.0
        self._hover = False
        self._hover_value = 0.0
        self._start_value = 0.0
        self.on_seek = on_seek
        self.on_hover = on_hover
        self.set_hexpand(True)
        self.set_size_request(-1, 30)
        self.set_draw_func(self._draw)
        self.add_css_class("seekbar")
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.add_controller(motion)

    def set_state(self, position, duration, buffered) -> None:
        self.position = position or 0.0
        self.duration = duration or 0.0
        self.buffered = buffered or 0.0
        self.queue_draw()

    def _x_to_value(self, x: float) -> float:
        width = max(1, self.get_width())
        if not self.duration:
            return 0.0
        return max(0.0, min(1.0, x / width)) * self.duration

    def _drag_begin(self, _gesture, x, _y) -> None:
        if not self.duration:
            return
        self.scrubbing = True
        self._start_value = self._x_to_value(x)
        self.scrub_value = self._start_value
        self.on_hover(True, self.scrub_value)
        self.queue_draw()

    def _drag_update(self, _gesture, offset_x, _y) -> None:
        if not self.scrubbing:
            return
        width = max(1, self.get_width())
        self.scrub_value = max(0.0, min(self.duration, self._start_value + offset_x / width * self.duration))
        self.on_hover(True, self.scrub_value)
        self.queue_draw()

    def _drag_end(self, _gesture, _offset_x, _offset_y) -> None:
        if not self.scrubbing:
            return
        self.scrubbing = False
        self.on_hover(False, self.scrub_value)
        value = self.scrub_value
        self.queue_draw()
        self.on_seek(value)

    def _motion(self, _controller, x, _y) -> None:
        if not self.duration:
            return
        self._hover = True
        self._hover_value = self._x_to_value(x)
        if not self.scrubbing:
            self.on_hover(True, self._hover_value)
        self.queue_draw()

    def _leave(self, _controller) -> None:
        self._hover = False
        if not self.scrubbing:
            self.on_hover(False, 0.0)
        self.queue_draw()

    def _draw(self, _widget, cr, width, height) -> None:
        color = self.get_color()
        accent = (color.red, color.green, color.blue)
        track_h = 6.0
        y = (height - track_h) / 2
        radius = track_h / 2
        cr.set_source_rgba(*accent, 0.16)
        self._rounded(cr, 0, y, width, track_h, radius)
        cr.fill()
        if self.duration > 0:
            frac = min(1.0, self.buffered / self.duration) if self.buffered else 0.0
            if frac > 0:
                cr.set_source_rgba(*accent, 0.32)
                self._rounded(cr, 0, y, max(track_h, width * frac), track_h, radius)
                cr.fill()
            value = self.scrub_value if self.scrubbing else self.position
            frac = max(0.0, min(1.0, value / self.duration))
            cr.set_source_rgba(*accent, 1.0)
            self._rounded(cr, 0, y, max(track_h if frac > 0 else 0, width * frac), track_h, radius)
            cr.fill()
            knob_r = 9.0 if (self._hover or self.scrubbing) else 7.0
            knob_x = max(knob_r, min(width - knob_r, width * frac))
            cr.set_source_rgba(*accent, 1.0)
            cr.arc(knob_x, height / 2, knob_r, 0, 6.2832)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.92)
            cr.arc(knob_x, height / 2, knob_r - 3.0, 0, 6.2832)
            cr.fill()
            cr.set_source_rgba(*accent, 1.0)
            cr.arc(knob_x, height / 2, knob_r - 4.5, 0, 6.2832)
            cr.fill()

    @staticmethod
    def _rounded(cr, x, y, width, height, radius) -> None:
        if width <= 0:
            return
        radius = min(radius, width / 2, height / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        cr.close_path()


class BufferHealthGraph(Gtk.DrawingArea):
    """Compact time series of measured HLS buffer health (#133).

    The area is signed buffer-ahead seconds (positive = encoder ahead of the
    receiver), the thin line is the available HLS segment count and red marks
    are watchdog restarts. It only reads the bounded history supplied by the
    existing GUI tick; it never polls, reads disk or controls a receiver.
    """

    _STALL = (0.93, 0.28, 0.24)
    _SEGMENTS = (0.55, 0.78, 0.98)

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 58)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        self.set_tooltip_text(
            "Measured HLS buffer health: area is buffer ahead/behind, "
            "line is available segments, red marks are watchdog restarts."
        )
        self._samples: tuple = ()

    def set_health(self, health) -> None:
        """Show the supplied :class:`buffer_health.BufferHealth` history."""
        self._samples = health.samples
        self.queue_draw()

    def _draw(self, _widget, cr, width: int, height: int) -> None:
        fg = self.get_color()
        pad = 6.0
        plot_w = max(1.0, width - pad * 2)
        plot_h = max(1.0, height - pad * 2)
        mid = pad + plot_h / 2.0
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.06)
        SeekBar._rounded(cr, 0, 0, width, height, 8)
        cr.fill()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.22)
        cr.set_line_width(1)
        cr.move_to(pad, mid)
        cr.line_to(pad + plot_w, mid)
        cr.stroke()
        if len(self._samples) < 2:
            return
        ahead = [sample[0] for sample in self._samples]
        segments = [sample[1] for sample in self._samples]
        known = [value for value in ahead if value is not None]
        scale = max((abs(value) for value in known), default=0.0) or 1.0
        step = plot_w / (len(self._samples) - 1)

        def x_at(index: int) -> float:
            return pad + index * step

        def y_ahead(value: float) -> float:
            return mid - (value / scale) * (plot_h / 2.0)

        cr.new_path()
        cr.move_to(x_at(0), mid)
        previous = None
        for index, value in enumerate(ahead):
            if value is None:
                if previous is not None:
                    cr.line_to(x_at(index), mid)
                previous = None
                continue
            if previous is None:
                cr.line_to(x_at(index), mid)
            cr.line_to(x_at(index), y_ahead(value))
            previous = value
        cr.line_to(x_at(len(ahead) - 1), mid)
        cr.close_path()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.20)
        cr.fill()

        cr.new_path()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.85)
        cr.set_line_width(1.5)
        started = False
        for index, value in enumerate(ahead):
            if value is None:
                started = False
                continue
            if not started:
                cr.move_to(x_at(index), y_ahead(value))
                started = True
            else:
                cr.line_to(x_at(index), y_ahead(value))
        cr.stroke()

        top_segments = max(segments, default=0) or 1
        cr.new_path()
        cr.set_source_rgba(*self._SEGMENTS, 0.65)
        cr.set_line_width(1.0)
        for index, count in enumerate(segments):
            y = pad + plot_h - (count / top_segments) * plot_h
            if index == 0:
                cr.move_to(x_at(index), y)
            else:
                cr.line_to(x_at(index), y)
        cr.stroke()

        for index, sample in enumerate(self._samples):
            if not sample[2]:
                continue
            cr.set_source_rgba(*self._STALL, 0.95)
            cr.set_line_width(2.0)
            cr.move_to(x_at(index), pad)
            cr.line_to(x_at(index), pad + plot_h)
            cr.stroke()


class LevelMeter(Gtk.DrawingArea):
    """DJM-style segmented LED meters for the dialogue compressor.

    Draws four horizontal segmented bars (input L/R, output L/R) plus a
    diverging PUMP / GAIN strip showing how far the dialogue chain is lifting
    or pulling the signal.  A MASTER bouncing-line meter sits at the bottom:
    a single bright line whose horizontal reach is the post-compressor output
    level, so you can see at a glance how close the *played-back* signal is to
    0 dBFS.  Samples are pushed in from the audio monitor thread via
    :meth:`set_sample` (marshalled onto the main thread by the caller).  A
    short animation timer (~40 fps) eases the displayed bars toward each new
    target with real-meter ballistics (fast attack, slow release) so the
    display glides smoothly between analysis windows instead of jumping and
    flickering.  The timer stops once everything settles to keep CPU idle.
    With no sample the meter eases to a dim "no signal" state and never
    touches playback.
    """

    SEGMENTS = 26
    FLOOR_DB = -60.0
    PUMP_RANGE = 24.0
    _LABEL_W = 48.0
    _ROW_H = 15.0
    _ROW_GAP = 4.0
    _MASTER_H = 18.0

    # Animation ballistics — fast rise, slow fall (like a real VU/PPM meter).
    _ATTACK = 0.55
    _RELEASE = 0.16
    # When every value is within this many dB of its target, snap and stop.
    _SETTLE_DB = 0.35
    _SETTLE_GAIN = 0.12
    _TICK_MS = 25  # ~40 fps

    _GREEN = (0.24, 0.78, 0.36)
    _YELLOW = (0.98, 0.80, 0.16)
    _RED = (0.93, 0.28, 0.24)
    _BLUE = (0.30, 0.62, 0.95)
    _ORANGE = (0.99, 0.60, 0.18)
    _DIM = (1.0, 1.0, 1.0, 0.07)
    _WHITE = (1.0, 1.0, 1.0)

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_size_request(-1, 144)
        self.set_draw_func(self._draw)
        self.connect("unrealize", self._on_unrealize)
        self._gtk_settings = Gtk.Settings.get_default()
        if self._gtk_settings is not None:
            # Weakly bound to the widget, not a global settings leak.
            self._gtk_settings.connect_object(
                "notify::gtk-enable-animations", self._on_motion_changed, self)
        self._lock = threading.Lock()
        self._target = None       # newest sample from the analysis thread
        self._disp = None         # eased values actually drawn
        self._gain = 0.0
        self._gain_target = 0.0
        self._master = self.FLOOR_DB   # eased master output level (dBFS)
        self._master_target = self.FLOOR_DB
        self._timer = 0           # GLib animation timer id (0 = stopped)

    def _on_unrealize(self, _widget) -> None:
        if self._timer != 0:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _on_motion_changed(self, *_args) -> None:
        if not idle_chrome.animations_enabled(self._gtk_settings):
            self._start_or_snap()

    def _start_or_snap(self) -> None:
        """No animation timer while reduced motion is preferred."""
        if not idle_chrome.animations_enabled(self._gtk_settings):
            if self._timer:
                GLib.source_remove(self._timer)
                self._timer = 0
            with self._lock:
                self._disp = self._target
                self._gain = self._gain_target
                self._master = self._master_target
            self.queue_draw()
        elif self._timer == 0:
            self._timer = GLib.timeout_add(self._TICK_MS, self._animate)

    def set_sample(self, sample) -> None:
        """Store the newest analysis window as the animation target.

        Does not redraw immediately — the animation timer picks up the new
        target and eases toward it, which is what produces smooth, flicker-free
        motion.  Starts the timer if it is not already running.
        """
        with self._lock:
            self._target = sample
            if sample is not None:
                self._gain_target = float(sample.gain_db)
                self._master_target = float(sample.out_rms)
            else:
                self._gain_target = 0.0
                self._master_target = self.FLOOR_DB
        self._start_or_snap()

    def reset(self) -> None:
        """Ease back to silence (no signal)."""
        with self._lock:
            self._target = None
            self._gain_target = 0.0
            self._master_target = self.FLOOR_DB
        self._start_or_snap()

    def _animate(self) -> bool:
        """One animation step: ease displayed values toward target."""
        with self._lock:
            target = self._target
            disp = self._disp
            moving = False

            if target is not None:
                if disp is None:
                    # First sample: snap (no animation from nothing).
                    self._disp = target
                    moving = True
                else:
                    self._disp = self._ease_sample(disp, target)
                    if self._sample_distance(self._disp, target) > self._SETTLE_DB:
                        moving = True
                    else:
                        self._disp = target
            else:
                # No target: ease toward silence.
                if disp is not None:
                    silent = audio_monitor.LevelSample(
                        self.FLOOR_DB, self.FLOOR_DB,
                        self.FLOOR_DB, self.FLOOR_DB,
                        self.FLOOR_DB, self.FLOOR_DB,
                        self.FLOOR_DB, self.FLOOR_DB,
                    )
                    self._disp = self._ease_sample(disp, silent)
                    if self._sample_distance(self._disp, silent) > self._SETTLE_DB:
                        moving = True
                    else:
                        self._disp = None
                else:
                    moving = False

            # Ease the pump needle.
            gain_diff = abs(self._gain_target - self._gain)
            if gain_diff > self._SETTLE_GAIN:
                factor = self._ATTACK if self._gain_target > self._gain else self._RELEASE
                self._gain += (self._gain_target - self._gain) * factor
                moving = True
            else:
                self._gain = self._gain_target

            # Ease the master bouncing line.
            master_diff = abs(self._master_target - self._master)
            if master_diff > self._SETTLE_DB:
                factor = self._ATTACK if self._master_target > self._master else self._RELEASE
                self._master += (self._master_target - self._master) * factor
                moving = True
            else:
                self._master = self._master_target

        if moving:
            self.queue_draw()
            return True
        self._timer = 0
        return False

    @classmethod
    def _ease_sample(cls, current, target):
        """Ease each level of *current* toward *target* with attack/release."""
        def ease(c, t):
            if t > c:
                return c + (t - c) * cls._ATTACK
            return c + (t - c) * cls._RELEASE
        return audio_monitor.LevelSample(
            ease(current.in_rms, target.in_rms),
            ease(current.out_rms, target.out_rms),
            ease(current.in_peak, target.in_peak),
            ease(current.out_peak, target.out_peak),
            ease(current.in_l, target.in_l),
            ease(current.in_r, target.in_r),
            ease(current.out_l, target.out_l),
            ease(current.out_r, target.out_r),
        )

    @staticmethod
    def _sample_distance(a, b) -> float:
        """Max absolute dB difference across all level pairs."""
        return max(
            abs(a.in_rms - b.in_rms), abs(a.out_rms - b.out_rms),
            abs(a.in_l - b.in_l), abs(a.in_r - b.in_r),
            abs(a.out_l - b.out_l), abs(a.out_r - b.out_r),
        )

    # ---- drawing helpers ----

    @staticmethod
    def _seg_color(top_db: float):
        if top_db >= -6.0:
            return LevelMeter._RED
        if top_db >= -18.0:
            return LevelMeter._YELLOW
        return LevelMeter._GREEN

    def _draw_levels(self, cr, x, y, width, height, value) -> None:
        seg_pitch = width / self.SEGMENTS
        seg_w = max(1.0, seg_pitch - 1.6)
        frac = 0.0
        if value is not None:
            frac = (value - self.FLOOR_DB) / (0.0 - self.FLOOR_DB)
            frac = max(0.0, min(1.0, frac))
        lit = int(round(frac * self.SEGMENTS))
        radius = min(1.6, seg_w / 2, height / 2)
        for i in range(self.SEGMENTS):
            top_db = self.FLOOR_DB + (i + 1) / self.SEGMENTS * (0.0 - self.FLOOR_DB)
            seg_x = x + i * seg_pitch
            self._rounded(cr, seg_x, y, seg_w, height, radius)
            if value is not None and i < lit:
                cr.set_source_rgb(*self._seg_color(top_db))
            else:
                cr.set_source_rgba(*self._DIM)
            cr.fill()

    def _draw_master(self, cr, x, y, width, height) -> None:
        """Bouncing-line master meter — shows how close the *output* is to 0.

        A single bright vertical line whose height is the post-compressor level
        (out_rms, eased with attack/release).  The line "bounces" toward each
        new target instead of jumping, so you can watch how close the signal
        is to 0 dBFS without the display flickering.  A faint 0 dBFS ceiling
        notch marks the top of the scale.
        """
        # Track background.
        self._rounded(cr, x, y, width, height, height / 2)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.05)
        cr.fill()
        # 0 dBFS ceiling notch.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.35)
        cr.rectangle(x + 1, y + 0.6, max(2.0, width - 2), 1.0)
        cr.fill()
        # -6 dB warning notch.
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.18)
        six_y = y + (1.0 - (-6.0 - self.FLOOR_DB) / (0.0 - self.FLOOR_DB)) * height
        cr.rectangle(x + 1, six_y, max(2.0, width - 2), 1.0)
        cr.fill()
        # Bouncing line.
        frac = (self._master - self.FLOOR_DB) / (0.0 - self.FLOOR_DB)
        frac = max(0.0, min(1.0, frac))
        line_h = max(2.0, frac * height)
        line_y = y + height - line_h
        # Glow under the line.
        cr.set_source_rgba(*self._ORANGE, 0.30)
        cr.rectangle(x + 2, line_y - 2, max(2.0, width - 4), line_h + 4)
        cr.fill()
        # The line itself — colour by how close to 0 it is.
        if self._master >= -6.0:
            color = self._RED
        elif self._master >= -18.0:
            color = self._YELLOW
        else:
            color = self._WHITE
        cr.set_source_rgb(*color)
        cr.rectangle(x + 3, line_y, max(3.0, width - 6), line_h)
        cr.fill()
        # Tip glow when very close to 0.
        if self._master >= -3.0:
            cr.set_source_rgba(*self._RED, 0.55)
            cr.arc(x + width / 2, line_y - 1.0, 4.0, 0, 6.2832)
            cr.fill()

    def _draw_pump(self, cr, x, y, width, height) -> None:
        center = x + width / 2
        half = width / 2
        gain = max(-self.PUMP_RANGE, min(self.PUMP_RANGE, self._gain))
        # faint full-range track with a centre notch
        self._rounded(cr, x, y, width, height, height / 2)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        cr.fill()
        if abs(gain) >= 0.4:
            reach = abs(gain) / self.PUMP_RANGE * half
            if gain >= 0:
                bx, color = center, (self._ORANGE if gain < 18 else self._RED)
            else:
                bx, color = center - reach, self._BLUE
            self._rounded(cr, min(bx, center), y, reach, height, height / 2)
            cr.set_source_rgb(*color)
            cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.55)
        cr.rectangle(center - 0.75, y - 1.5, 1.5, height + 3.0)
        cr.fill()

    def _draw(self, _widget, cr, width, height) -> None:
        with self._lock:
            sample = self._disp
            master = self._master
        rows = (
            ("IN L", sample.in_l if sample else None),
            ("IN R", sample.in_r if sample else None),
            ("OUT L", sample.out_l if sample else None),
            ("OUT R", sample.out_r if sample else None),
        )
        total_h = (len(rows) * self._ROW_H + (len(rows) - 1) * self._ROW_GAP
                   + self._ROW_GAP + self._MASTER_H + 20.0)
        top = max(0.0, (height - total_h) / 2)
        bar_x = self._LABEL_W
        bar_w = max(10.0, width - self._LABEL_W - 4.0)
        cr.select_font_face("Sans")
        cr.set_font_size(9.5)
        fg = self.get_color()
        for index, (label, value) in enumerate(rows):
            row_y = top + index * (self._ROW_H + self._ROW_GAP)
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.78)
            cr.move_to(0, row_y + self._ROW_H - 3.5)
            cr.show_text(label)
            self._draw_levels(cr, bar_x, row_y, bar_w, self._ROW_H, value)
        # pump / gain strip
        pump_y = top + len(rows) * (self._ROW_H + self._ROW_GAP) + 2.0
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.78)
        cr.move_to(0, pump_y + 10.0)
        cr.show_text("PUMP")
        self._draw_pump(cr, bar_x, pump_y, bar_w, 12.0)
        gain_text = "—" if sample is None else f"{self._gain:+.1f} dB"
        cr.set_font_size(8.5)
        ext = cr.text_extents(gain_text)
        gx = max(bar_x, bar_x + bar_w - ext.width)
        cr.rectangle(gx - 3, pump_y - 1.5, ext.width + 6, 15.0)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
        cr.fill()
        if sample is None:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.5)
        elif self._gain >= 0:
            cr.set_source_rgb(*self._ORANGE)
        else:
            cr.set_source_rgb(*self._BLUE)
        cr.move_to(gx, pump_y + 10.0)
        cr.show_text(gain_text)
        # Master bouncing line: a single post-processing output indicator.
        master_y = pump_y + 16.0
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.78)
        cr.move_to(0, master_y + self._MASTER_H - 3.0)
        cr.show_text("MASTER")
        self._draw_master(cr, bar_x, master_y, bar_w, self._MASTER_H)
        master_text = f"{master:+.1f} dBFS"
        cr.set_font_size(8.5)
        ext = cr.text_extents(master_text)
        mx = max(bar_x, bar_x + bar_w - ext.width)
        cr.rectangle(mx - 3, master_y - 1.0, ext.width + 6, self._MASTER_H + 2.0)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
        cr.fill()
        if sample is None:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.5)
        elif master >= -6.0:
            cr.set_source_rgb(*self._RED)
        elif master >= -18.0:
            cr.set_source_rgb(*self._YELLOW)
        else:
            cr.set_source_rgb(*self._WHITE)
        cr.move_to(mx, master_y + self._MASTER_H / 2)
        cr.show_text(master_text)
    @staticmethod
    def _rounded(cr, x, y, width, height, radius) -> None:
        if width <= 0 or height <= 0:
            return
        radius = min(radius, width / 2, height / 2)
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        cr.close_path()


class PreviewScreen(Gtk.DrawingArea):
    """Video preview screen shown above the scrubbing bar.

    Shows a colored placeholder with video title/info when no thumbnail is
    available.  Keeps the UI responsive — all drawing is local, no blocking
    I/O on the main thread.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(-1, 120)
        self.set_draw_func(self._draw)
        self._lock = threading.Lock()
        self._title = "No video"
        self._info = ""
        self._color = (0.15, 0.15, 0.20)

    def set_video(self, title: str, info: str, color: tuple = (0.15, 0.15, 0.20)) -> None:
        """Update the preview with video metadata."""
        with self._lock:
            self._title = title
            self._info = info
            self._color = color
        self.queue_draw()

    def _draw(self, _widget, cr, width, height) -> None:
        """Render a purposeful film slate rather than an empty grey rectangle."""
        with self._lock:
            title, info = self._title, self._info
        if width <= 0 or height <= 0:
            return
        cr.save()
        cr.rectangle(0, 0, width, height)
        cr.clip()
        cr.set_source_rgb(0.064, 0.112, 0.179)
        cr.paint()
        for step in range(10):
            cr.set_source_rgba(0.47, 0.75, 1.0, 0.012 + 0.004 * (10 - step))
            cr.rectangle(width * (0.53 + step * 0.046), 0, width * 0.024, height)
            cr.fill()
        cr.set_source_rgba(0.48, 0.73, 1.0, 0.34)
        cr.rectangle(0, 0, min(width, 5), height)
        cr.fill()
        empty = not title or title == "No video"
        cx = width / 2 if empty else min(64, width * 0.16)
        cy = height * (0.35 if empty else 0.50)
        radius = min(30.0, max(17.0, min(width, height) * 0.18))
        cr.set_source_rgba(0.42, 0.69, 1.0, 0.14)
        cr.arc(cx, cy, radius + 10, 0, 6.283185)
        cr.fill()
        cr.set_source_rgba(0.51, 0.77, 1.0, 0.95)
        cr.arc(cx, cy, radius, 0, 6.283185)
        cr.fill()
        cr.set_source_rgb(0.068, 0.15, 0.24)
        cr.move_to(cx - radius * 0.23, cy - radius * 0.45)
        cr.line_to(cx - radius * 0.23, cy + radius * 0.45)
        cr.line_to(cx + radius * 0.50, cy)
        cr.close_path()
        cr.fill()

        def fit(value: str, limit: float) -> str:
            if limit < 12:
                return ""
            if cr.text_extents(value).width <= limit:
                return value
            lo, hi = 0, len(value)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if cr.text_extents(value[:mid] + "…").width <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            return value[:lo] + "…" if lo else ""

        cr.select_font_face("Sans")
        cr.set_font_size(17 if height >= 140 else 14)
        heading = "Video preview" if empty else title
        if empty:
            display_title = fit(heading, width - 30)
            text_x = max(10, (width - cr.text_extents(display_title).width) / 2)
            text_y = min(height - 22, cy + radius + 30)
        else:
            text_x = min(width - 15, cx + radius + 27)
            display_title = fit(heading, width - text_x - 18)
            text_y = height * 0.50 + 1
        cr.set_source_rgb(0.93, 0.96, 1.0)
        cr.move_to(text_x, text_y)
        cr.show_text(display_title)
        subheading = "" if empty else info
        if subheading:
            cr.set_font_size(12)
            subtitle = fit(subheading, width - 32 if empty else width - text_x - 18)
            subtitle_x = max(10, (width - cr.text_extents(subtitle).width) / 2) if empty else text_x
            cr.set_source_rgb(0.66, 0.76, 0.89)
            cr.move_to(subtitle_x, min(height - 9, text_y + 22))
            cr.show_text(subtitle)
        cr.restore()
        cr.set_source_rgba(0.47, 0.67, 0.9, 0.25)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, max(0, width - 1), max(0, height - 1))
        cr.stroke()
