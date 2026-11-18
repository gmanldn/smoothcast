#!/usr/bin/env python3
"""Cast Control — modern Chromecast companion."""
from __future__ import annotations

import json
import pathlib
import re
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

import castctl
import streamer
import audio_monitor

APP_ID = "local.cast-control"
APP_NAME = "Cast Control"
CONFIG_DIR = pathlib.Path(GLib.get_user_config_dir()) / "cast-control"
CONFIG_FILE = CONFIG_DIR / "config.json"
ICON_NAME = "cast-control"

DEFAULTS: dict = {
    "device": castctl.DEFAULT_DEVICE,
    "quality": "balanced",
    "audio": "dialogue",
    "audio_gain": 6.0,
    "subs": "auto",
    "subs_path": "",
    "burn_subs": False,
    "direct": True,
    "autonext": False,
    "keep_streaming": True,
    "color_scheme": "prefer-dark",
    "recents": [],
    "window_width": 1120,
    "window_height": 760,
}

CSS = """
window { font-size: 14px; }
.card { background-color: @card_bg_color; border-radius: 18px; padding: 14px; }
.chip { border-radius: 99px; padding: 2px 12px; font-weight: 600; font-size: 0.82em; }
.chip.idle { background-color: alpha(@view_fg_color, 0.10); }
.chip.playing, .chip.buffering { background-color: @accent_bg_color; color: @accent_fg_color; }
.chip.paused { background-color: @warning_bg_color; color: @warning_fg_color; }
.chip.offline, .chip.error { background-color: @error_bg_color; color: @error_fg_color; }
.pill { border-radius: 99px; font-weight: 600; min-width: 50px; padding: 4px 6px; }
.big-play { min-width: 64px; min-height: 64px; border-radius: 99px; }
.transport { min-width: 40px; min-height: 40px; border-radius: 99px; }
.seekbar { color: @accent_bg_color; }
.queue-title { font-weight: 600; }
.queue-row.current .queue-title { color: @accent_color; }
.detail-key { color: alpha(@view_fg_color, 0.55); }
.detail-value { font-feature-settings: "tnum"; }
.mono { font-family: monospace; font-size: 0.9em; }
""".encode()


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_FILE.read_text())
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=1))
        tmp.replace(CONFIG_FILE)
    except OSError:
        pass


def pretty_title(path: pathlib.Path) -> str:
    stem = re.sub(r"[._]+", " ", path.stem).strip()
    stem = re.sub(r"\s+(19|20)\d\d\s*$", "", stem).strip()
    return stem or path.name


def fmt_time(seconds: float | None) -> str:
    return castctl.fmt_time(seconds)


class Async:
    @staticmethod
    def run(work, done=None, failed=None):
        def runner():
            try:
                result = work()
            except Exception as exc:
                if failed is not None:
                    GLib.idle_add(failed, str(exc))
                return
            if done is not None:
                GLib.idle_add(done, result)

        threading.Thread(target=runner, daemon=True).start()


class PositionTracker:
    def __init__(self) -> None:
        self.known = False
        self.duration = 0.0
        self._base = 0.0
        self._epoch = time.monotonic()
        self._playing = False
        self._paused_accum = 0.0
        self._pause_started: float | None = None

    def start(self, base: float, duration: float, playing: bool = True) -> None:
        self.known = True
        self.duration = duration or self.duration
        self._base = max(0.0, base)
        self._epoch = time.monotonic()
        self._playing = playing
        self._paused_accum = 0.0
        self._pause_started = None

    def set_state(self, playing: bool) -> None:
        if playing == self._playing:
            return
        now = time.monotonic()
        if playing:
            if self._pause_started is not None:
                self._paused_accum += now - self._pause_started
                self._pause_started = None
        else:
            self._pause_started = now
        self._playing = playing

    def device_update(self, current: float, duration: float | None) -> None:
        self.start(current, duration or self.duration, self._playing)

    def rebase(self, value: float) -> None:
        self.start(value, self.duration, self._playing)

    def value(self, now: float | None = None) -> float | None:
        if not self.known:
            return None
        now = now or time.monotonic()
        paused = self._paused_accum
        if self._pause_started is not None:
            paused += now - self._pause_started
        value = self._base + (now - self._epoch - paused)
        if self.duration:
            value = min(value, self.duration)
        return max(0.0, value)

    def clear(self) -> None:
        self.known = False
        self.duration = 0.0
        self._playing = False
        self._paused_accum = 0.0
        self._pause_started = None


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
        self.set_size_request(-1, 156)
        self.set_draw_func(self._draw)
        self.connect("unrealize", self._on_unrealize)
        self._lock = threading.Lock()
        self._target = None       # newest sample from the analysis thread
        self._disp = None         # eased values actually drawn
        self._gain = 0.0
        self._gain_target = 0.0
        self._master = FLOOR_DB   # eased master output level (dBFS)
        self._master_target = FLOOR_DB
        self._timer = 0           # GLib animation timer id (0 = stopped)

    def _on_unrealize(self, _widget) -> None:
        if self._timer != 0:
            GLib.source_remove(self._timer)
            self._timer = 0

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
        if self._timer == 0:
            self._timer = GLib.timeout_add(self._TICK_MS, self._animate)

    def reset(self) -> None:
        """Ease back to silence (no signal)."""
        with self._lock:
            self._target = None
            self._gain_target = 0.0
            self._master_target = self.FLOOR_DB
        if self._timer == 0:
            self._timer = GLib.timeout_add(self._TICK_MS, self._animate)

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
        rows = (
            ("IN L", sample.in_l if sample else None),
            ("IN R", sample.in_r if sample else None),
            ("OUT L", sample.out_l if sample else None),
            ("OUT R", sample.out_r if sample else None),
        )
        total_h = len(rows) * self._ROW_H + (len(rows) - 1) * self._ROW_GAP + self._ROW_GAP + 13.0
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


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app) -> None:
        super().__init__(application=app)
        self.app = app
        self.cfg = load_config()
        self.session: streamer.Session | None = None
        self.media: streamer.MediaInfo | None = None
        self.device_info: dict | None = None
        self.devices: list[castctl.Device] = []
        self.device_state = "IDLE"
        self.external = False
        self.busy = False
        self.poll_busy = False
        self.scan_busy = False
        self.queue: list[str] = []
        self.queue_durations: dict[str, float] = {}
        self.now_playing: str | None = None
        self.selected_index: int | None = None
        self.tracker = PositionTracker()
        self._volume_job: int | None = None
        self._volume_user_ts = 0.0
        self._syncing = False
        self._subs_cache: tuple[str, str | None] = ("", None)
        self._hover_time: float | None = None
        self._finished_handled = False
        self._last_state = "IDLE"
        self._play_icon_name = "media-playback-start-symbolic"
        self.meter: LevelMeter | None = None
        self.monitor: audio_monitor.AudioMonitor | None = None
        self._mon_path: pathlib.Path | None = None
        self._mon_chain: list[str] = []

        self.set_default_size(self.cfg["window_width"], self.cfg["window_height"])
        self.set_size_request(880, 560)
        self._build_ui()
        self._refresh_direct_note()
        self.connect("close-request", self._on_close)
        self._install_shortcuts()
        self._apply_color_scheme()
        self._refresh_controls()
        GLib.timeout_add(500, self._tick)
        GLib.timeout_add(100, self._meter_tick)
        GLib.timeout_add(900, lambda: (self._poll_device(), False)[1])
        GLib.timeout_add(4000, self._poll_device)
        GLib.timeout_add(400, self._initial_scan)
        GLib.timeout_add(600, self._adopt_session)

    def _build_ui(self) -> None:
        self.set_title(APP_NAME)
        header = Adw.HeaderBar()
        self.title_widget = Adw.WindowTitle(title=APP_NAME, subtitle=self.cfg["device"])
        header.set_title_widget(self.title_widget)
        _icon_path = pathlib.Path(__file__).resolve().parent.parent / "data" / "cast-control.png"
        if _icon_path.exists():
            icon = Gtk.Image.new_from_file(str(_icon_path))
        else:
            icon = Gtk.Image.new_from_icon_name("cast-control")
        icon.set_pixel_size(22)
        header.pack_start(icon)
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Main menu")
        menu_button.set_menu_model(self._build_menu())
        header.pack_end(menu_button)
        self.menu_button = menu_button

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(False)
        paned.set_shrink_end_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.set_hexpand(True)
        left.append(self._build_now_playing())
        left.append(self._build_live_levels())
        left.append(self._build_queue())
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        right_box.set_size_request(330, -1)
        right_box.append(self._build_device_card())
        right_box.append(self._build_settings_card())
        right_box.append(self._build_details_card())
        right_scroller = Gtk.ScrolledWindow()
        right_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        right_scroller.set_child(right_box)
        right_scroller.set_size_request(346, -1)
        paned.set_start_child(left)
        paned.set_end_child(right_scroller)
        paned.set_position(700)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.set_margin_top(14)
        holder.set_margin_bottom(14)
        holder.set_margin_start(14)
        holder.set_margin_end(14)
        holder.append(paned)
        toolbar.set_content(holder)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Open video…", "app.open")
        section.append("Add videos to queue…", "app.add-files")
        menu.append_section(None, section)
        recents = Gio.Menu()
        for index, path in enumerate(self.cfg["recents"][:8]):
            recents.append(pathlib.Path(path).name, f"app.recent-{index}")
        menu.append_submenu("Open recent", recents)
        playback = Gio.Menu()
        playback.append("Stop stream", "app.stop-stream")
        menu.append_section(None, playback)
        scheme = Gio.Menu()
        for label, value in (("Follow system", "default"), ("Light", "force-light"), ("Dark", "prefer-dark")):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value("app.color-scheme", GLib.Variant("s", value))
            scheme.append_item(item)
        menu.append_submenu("Appearance", scheme)
        help_menu = Gio.Menu()
        help_menu.append("Keyboard shortcuts", "app.shortcuts")
        help_menu.append("About Cast Control", "app.about")
        help_menu.append("Quit", "app.quit")
        menu.append_section(None, help_menu)
        return menu

    def _card(self, title: str, subtitle: str = "") -> tuple[Gtk.Box, Gtk.Box]:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("card")
        heading = Gtk.Label(label=title, xalign=0.0)
        heading.add_css_class("heading")
        card.append(heading)
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
            sub.add_css_class("dim-label")
            sub.add_css_class("caption")
            card.append(sub)
        return card, card

    def _build_now_playing(self) -> Gtk.Box:
        card, body = self._card("Now Playing")
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.np_title = Gtk.Label(label="Nothing selected", xalign=0.0, hexpand=True, ellipsize=3)
        self.np_title.add_css_class("title-3")
        self.state_chip = Gtk.Label(label="Ready")
        self.state_chip.add_css_class("chip")
        self.state_chip.add_css_class("idle")
        title_row.append(self.np_title)
        title_row.append(self.state_chip)
        body.append(title_row)
        self.np_meta = Gtk.Label(label="Choose a video to begin", xalign=0.0, wrap=True)
        self.np_meta.add_css_class("dim-label")
        self.np_meta.add_css_class("caption")
        body.append(self.np_meta)
        self.seekbar = SeekBar(self.seek_to, self._on_hover)
        body.append(self.seekbar)
        clock_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.elapsed_label = Gtk.Label(label="0:00:00", xalign=0.0, hexpand=True)
        self.elapsed_label.add_css_class("caption")
        self.elapsed_label.add_css_class("mono")
        self.remaining_label = Gtk.Label(label="--:--")
        self.remaining_label.add_css_class("caption")
        self.remaining_label.add_css_class("mono")
        self.remaining_label.add_css_class("dim-label")
        clock_row.append(self.elapsed_label)
        clock_row.append(self.remaining_label)
        body.append(clock_row)

        transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        transport.set_halign(Gtk.Align.CENTER)
        self.prev_button = self._icon_button("go-previous-symbolic", "Previous in queue (P)", "transport", self.on_prev, size=18)
        self.back30_button = self._text_button("−30", "Back 30 seconds (Shift+←)", self._skip_back30)
        self.back10_button = self._text_button("−10", "Back 10 seconds (←)", self._skip_back10)
        self.play_button = Gtk.Button()
        self.play_button.add_css_class("suggested-action")
        self.play_button.add_css_class("big-play")
        self.play_image = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        self.play_image.set_pixel_size(26)
        self.play_button.set_child(self.play_image)
        self.play_button.set_tooltip_text("Play / Pause (Space)")
        self.play_button.connect("clicked", lambda _b: self.toggle_play())
        self.fwd10_button = self._text_button("+10", "Forward 10 seconds (→)", self._skip_forward10)
        self.fwd30_button = self._text_button("+30", "Forward 30 seconds (Shift+→)", self._skip_forward30)
        self.next_button = self._icon_button("go-next-symbolic", "Next in queue (N)", "transport", self.on_next, size=18)
        self.stop_button = self._icon_button("media-playback-stop-symbolic", "Stop (S)", "transport", self.stop_stream, size=18)
        for widget in (self.prev_button, self.back30_button, self.back10_button,
                       self.play_button, self.fwd10_button, self.fwd30_button,
                       self.next_button, self.stop_button):
            transport.append(widget)
        body.append(transport)

        volume_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.mute_button = Gtk.ToggleButton()
        self.mute_button.set_icon_name("audio-volume-high-symbolic")
        self.mute_button.set_tooltip_text("Mute (M)")
        self.mute_button.add_css_class("flat")
        self.mute_button.connect("toggled", self._on_mute)
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_hexpand(True)
        self._syncing = True
        self.volume_scale.set_value(50)
        self._syncing = False
        self.volume_scale.connect("value-changed", self._on_volume_changed)
        self.volume_label = Gtk.Label(label="50%")
        self.volume_label.add_css_class("caption")
        self.volume_label.add_css_class("mono")
        self.volume_label.set_width_chars(4)
        volume_row.append(self.mute_button)
        volume_row.append(self.volume_scale)
        volume_row.append(self.volume_label)
        body.append(volume_row)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        open_button = Gtk.Button(label="Open video…")
        open_button.set_icon_name("folder-open-symbolic")
        open_button.connect("clicked", lambda _b: self.open_video())
        self.cast_button = Gtk.Button(label="Cast")
        self.cast_button.set_icon_name("send-to-symbolic")
        self.cast_button.add_css_class("suggested-action")
        self.cast_button.set_hexpand(True)
        self.cast_button.connect("clicked", lambda _b: self.cast_selected())
        self.cc_button = Gtk.ToggleButton(label="CC")
        self.cc_button.set_tooltip_text("Toggle captions on the TV")
        self.cc_button.connect("toggled", self._on_cc_toggled)
        action_row.append(open_button)
        action_row.append(self.cast_button)
        action_row.append(self.cc_button)
        body.append(action_row)
        return card

    def _build_live_levels(self) -> Gtk.Box:
        card, body = self._card("Live Levels")
        self.meter = LevelMeter()
        body.append(self.meter)
        self.levels_hint = Gtk.Label(label="")
        self.levels_hint.add_css_class("caption")
        self.levels_hint.add_css_class("dim-label")
        body.append(self.levels_hint)
        return card

    # ---------- audio monitor lifecycle ----------

    def _set_levels_hint(self, text: str) -> None:
        hint = getattr(self, "levels_hint", None)
        if hint is not None:
            hint.set_text(text)

    def _meter_tick(self) -> bool:
        mon = self.monitor
        meter = self.meter
        if mon is None or meter is None:
            if meter is not None:
                meter.set_sample(None)
            return True
        position = self.tracker.value()
        if position is None:
            meter.set_sample(None)
        else:
            meter.set_sample(mon.sample_at(position))
        return True

    def _start_monitor(self, media_path, offset: float, chain) -> None:
        self._stop_monitor()
        if media_path is None:
            return
        try:
            self._mon_path = pathlib.Path(media_path)
            self._mon_chain = list(chain)
            self.monitor = audio_monitor.AudioMonitor()
            self.monitor.start(self._mon_path, self._mon_chain, offset=max(0.0, offset))
        except Exception:
            self.monitor = None

    def _resume_monitor(self) -> None:
        if self._mon_path is None or self.media is None:
            return
        if not (self.session and self.session.active()):
            return
        pos = self.tracker.value() or 0.0
        self._start_monitor(self._mon_path, pos, self._mon_chain)

    def _stop_monitor(self, reset: bool = True) -> None:
        mon, self.monitor = self.monitor, None
        if mon is not None:
            try:
                mon.stop()
            except Exception:
                pass
        if reset and self.meter is not None:
            self.meter.reset()

    def _build_queue(self) -> Gtk.Box:
        card, body = self._card("Up Next")
        card.set_vexpand(True)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_button = self._icon_button("list-add-symbolic", "Add videos…", "flat", self.add_files)
        clear_button = self._icon_button("edit-clear-all-symbolic", "Clear queue", "flat", self.clear_queue)
        toolbar.append(add_button)
        toolbar.append(clear_button)
        toolbar.append(Gtk.Box(hexpand=True))
        auto_label = Gtk.Label(label="Auto-play next")
        auto_label.add_css_class("caption")
        self.autonext_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.autonext_switch.set_active(bool(self.cfg["autonext"]))
        self.autonext_switch.connect("notify::active", self._on_autonext)
        toolbar.append(auto_label)
        toolbar.append(self.autonext_switch)
        body.append(toolbar)
        self.queue_summary = Gtk.Label(label="", xalign=0.0)
        self.queue_summary.add_css_class("dim-label")
        self.queue_summary.add_css_class("caption")
        self.queue_summary.set_visible(False)
        body.append(self.queue_summary)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_min_content_height(120)
        self.queue_list = Gtk.ListBox()
        self.queue_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.queue_list.add_css_class("boxed-list")
        self.queue_list.connect("row-activated", self._on_queue_activated)
        self.queue_list.connect("row-selected", self._on_queue_selected)
        scroller.set_child(self.queue_list)
        body.append(scroller)
        self.queue_empty = Gtk.Label(label="Queue is empty — add videos to build a playlist")
        self.queue_empty.add_css_class("dim-label")
        body.append(self.queue_empty)
        self._rebuild_queue()
        return card

    def _build_device_card(self) -> Gtk.Box:
        card, body = self._card("Device")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.device_dropdown = Gtk.DropDown.new_from_strings([self.cfg["device"]])
        self.device_dropdown.set_hexpand(True)
        self.device_dropdown.connect("notify::selected", self._on_device_selected)
        refresh = self._icon_button("view-refresh-symbolic", "Scan the network", "flat", self.scan_devices)
        row.append(self.device_dropdown)
        row.append(refresh)
        body.append(row)
        self.device_detail = Gtk.Label(label="Not scanned yet", xalign=0.0, wrap=True)
        self.device_detail.add_css_class("dim-label")
        self.device_detail.add_css_class("caption")
        body.append(self.device_detail)
        return card

    def _build_settings_card(self) -> Gtk.Box:
        card, body = self._card("Playback settings")
        self._syncing = True

        def dropdown_row(label, options, current, tooltip=""):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            tag = Gtk.Label(label=label, xalign=0.0, hexpand=True)
            dropdown = Gtk.DropDown.new_from_strings(options)
            dropdown.set_valign(Gtk.Align.CENTER)
            if tooltip:
                dropdown.set_tooltip_text(tooltip)
            row.append(tag)
            row.append(dropdown)
            body.append(row)
            return dropdown

        self.quality_dropdown = dropdown_row(
            "Video quality",
            ["High", "Balanced", "Data saver"],
            self.cfg["quality"],
            "Transcoding quality — applies on the next (re)start",
        )
        self.quality_dropdown.set_selected({"high": 0, "balanced": 1, "saver": 2}.get(self.cfg["quality"], 1))
        self.quality_dropdown.connect("notify::selected", self._on_quality)

        self.audio_dropdown = dropdown_row(
            "Sound profile",
            ["Original audio", "Dialogue auto-fix", "Night mode"],
            self.cfg["audio"],
            "Audio processing — applies on the next (re)start",
        )
        self.audio_dropdown.set_selected({"original": 0, "dialogue": 1, "night": 2}.get(self.cfg["audio"], 1))
        self.audio_dropdown.connect("notify::selected", self._on_audio)

        gain_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        gain_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        gain_text.set_hexpand(True)
        gain_title = Gtk.Label(label="Dialogue loudness boost", xalign=0.0)
        gain_title.set_tooltip_text("Extra loudness for quiet dialogue — type a value in dB (0–24). Applies on the next (re)start.")
        gain_sub = Gtk.Label(label="Levels loud bangs vs quiet speech; add dB here if you want it louder", xalign=0.0, wrap=True)
        gain_sub.add_css_class("dim-label")
        gain_sub.add_css_class("caption")
        gain_text.append(gain_title)
        gain_text.append(gain_sub)
        gain_adjustment = Gtk.Adjustment(
            value=float(self.cfg.get("audio_gain", DEFAULTS["audio_gain"])),
            lower=0, upper=24, step_increment=1, page_increment=3,
        )
        self.gain_spin = Gtk.SpinButton(adjustment=gain_adjustment, digits=0, climb_rate=1.0)
        self.gain_spin.set_valign(Gtk.Align.CENTER)
        self.gain_spin.set_tooltip_text("Type a boost in dB (0–24) and press Enter, or use the arrows")
        self.gain_spin.connect("value-changed", self._on_gain)
        gain_unit = Gtk.Label(label="dB", xalign=0.0)
        gain_unit.add_css_class("dim-label")
        gain_row.append(gain_text)
        gain_row.append(self.gain_spin)
        gain_row.append(gain_unit)
        body.append(gain_row)

        self.subs_dropdown = dropdown_row(
            "Subtitles",
            ["Off", "Auto (matching file)", "Pick file…"],
            self.cfg["subs"],
            "External subtitles served to the TV",
        )
        self.subs_dropdown.set_selected({"off": 0, "auto": 1, "pick": 2}.get(self.cfg["subs"], 1))
        self.subs_dropdown.connect("notify::selected", self._on_subs_mode)
        self.subs_detail = Gtk.Label(label="", xalign=0.0, wrap=True)
        self.subs_detail.add_css_class("dim-label")
        self.subs_detail.add_css_class("caption")
        body.append(self.subs_detail)

        burn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        burn_label = Gtk.Label(label="Burn subtitles into video", xalign=0.0, hexpand=True)
        burn_label.set_tooltip_text("Slower CPU encode — only if the TV cannot show CC tracks")
        self.burn_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.burn_switch.set_active(bool(self.cfg["burn_subs"]))
        self.burn_switch.connect("notify::active", self._on_burn)
        burn_row.append(burn_label)
        burn_row.append(self.burn_switch)
        body.append(burn_row)

        self.direct_switch = self._switch_row(
            body,
            "Direct play when possible",
            "Instant seeking for H.264/AAC files",
            bool(self.cfg["direct"]),
            self._on_direct,
        )
        self._switch_row(
            body,
            "Keep streaming after closing",
            "The TV keeps playing if the app exits",
            bool(self.cfg["keep_streaming"]),
            self._on_keep,
        )
        self._syncing = False
        return card

    def _switch_row(self, body, label, subtitle, active, callback) -> Gtk.Switch:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=label, xalign=0.0)
        sub = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        box.append(title)
        box.append(sub)
        box.set_hexpand(True)
        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.set_active(active)
        switch.connect("notify::active", callback)
        switch.subtitle_label = sub
        row.append(box)
        row.append(switch)
        body.append(row)
        return switch

    def _build_details_card(self) -> Gtk.Box:
        card, body = self._card("Stream details")
        grid = Gtk.Grid(row_spacing=6, column_spacing=12)
        grid.set_valign(Gtk.Align.START)
        self.detail_labels: dict[str, Gtk.Label] = {}
        rows = [
            ("state", "State"), ("mode", "Mode"), ("encoder", "Encoder"),
            ("position", "Position"), ("resolution", "Video"), ("audio", "Audio"),
            ("subs", "Subtitles"), ("file", "File"), ("url", "Stream URL"),
        ]
        for index, (key, label) in enumerate(rows):
            key_label = Gtk.Label(label=label, xalign=0.0)
            key_label.add_css_class("detail-key")
            key_label.add_css_class("caption")
            value_label = Gtk.Label(label="—", xalign=0.0, wrap=True, selectable=True)
            value_label.add_css_class("caption")
            value_label.add_css_class("detail-value")
            grid.attach(key_label, 0, index, 1, 1)
            grid.attach(value_label, 1, index, 1, 1)
            if key == "url":
                copy_button = self._icon_button("edit-copy-symbolic", "Copy stream URL", "flat", self._copy_url, size=14)
                copy_button.set_valign(Gtk.Align.START)
                copy_button.set_visible(False)
                grid.attach(copy_button, 2, index, 1, 1)
                self.copy_url_button = copy_button
            self.detail_labels[key] = value_label
        body.append(grid)
        return card

    def _copy_url(self) -> None:
        url = self.detail_labels["url"].get_text()
        if url and url != "—":
            self.get_clipboard().set(url)
            self.toast("Stream URL copied")

    def _icon_button(self, icon, tooltip, style_class, callback, size=16) -> Gtk.Button:
        button = Gtk.Button()
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(size)
        button.set_child(image)
        button.set_tooltip_text(tooltip)
        for cls in style_class.split():
            button.add_css_class(cls)
        button.connect("clicked", lambda _b: callback())
        return button

    def _text_button(self, label, tooltip, callback) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.set_tooltip_text(tooltip)
        button.add_css_class("pill")
        button.connect("clicked", lambda _b: callback())
        return button

    def _install_shortcuts(self) -> None:
        controller = Gtk.ShortcutController()

        def add(accel, callback):
            trigger = Gtk.ShortcutTrigger.parse_string(accel)
            action = Gtk.CallbackAction.new(lambda *args: (callback(), True)[1])
            controller.add_shortcut(Gtk.Shortcut.new(trigger, action))

        add("space", self.toggle_play)
        add("k", self.toggle_play)
        add("Left", self._skip_back10)
        add("Right", self._skip_forward10)
        add("<Shift>Left", self._skip_back30)
        add("<Shift>Right", self._skip_forward30)
        add("j", self._skip_back10)
        add("l", self._skip_forward10)
        add("m", self.toggle_mute)
        add("Up", lambda: self._nudge_volume(5))
        add("Down", lambda: self._nudge_volume(-5))
        add("s", self.stop_stream)
        add("n", self.on_next)
        add("p", self.on_prev)
        for digit in range(1, 10):
            add(str(digit), lambda d=digit: self._seek_percent(d))
        self.add_controller(controller)

    def _seek_percent(self, tenth: int) -> None:
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if duration:
            self.seek_to(duration * tenth / 10.0)

    def _apply_color_scheme(self) -> None:
        scheme = {
            "default": Adw.ColorScheme.DEFAULT,
            "force-light": Adw.ColorScheme.FORCE_LIGHT,
            "prefer-dark": Adw.ColorScheme.PREFER_DARK,
        }.get(self.cfg["color_scheme"], Adw.ColorScheme.PREFER_DARK)
        Adw.StyleManager.get_default().set_color_scheme(scheme)

    def toast(self, message: str, *, error: bool = False) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(3 if not error else 5)
        if error:
            toast.set_priority(Adw.ToastPriority.HIGH)
        self.toasts.add_toast(toast)

    # ---------- device helpers ----------

    def _device(self) -> str:
        return self.cfg["device"]

    def _initial_scan(self) -> bool:
        self.scan_devices()
        return False

    def scan_devices(self) -> None:
        if self.scan_busy:
            return
        self.scan_busy = True
        self.device_detail.set_text("Scanning…")
        Async.run(castctl.scan, done=self._scan_done, failed=lambda msg: self._scan_failed(msg))

    def _scan_done(self, devices) -> None:
        self.scan_busy = False
        self.devices = devices
        names = [d.name for d in devices]
        if self.cfg["device"] not in names:
            names.insert(0, self.cfg["device"])
        selected = names.index(self.cfg["device"])
        self._syncing = True
        self.device_dropdown.set_model(Gtk.StringList.new(names))
        self.device_dropdown.set_selected(selected)
        self._syncing = False
        if devices:
            info = next((d for d in devices if d.name == self.cfg["device"]), devices[0])
            self.device_detail.set_text(f"{info.model or 'Chromecast'} · {info.host}")
        else:
            self.device_detail.set_text("No Chromecasts found on this network")

    def _scan_failed(self, message) -> None:
        self.scan_busy = False
        self.device_detail.set_text("Scan failed — is the network reachable?")
        self.toast(str(message), error=True)

    def _on_device_selected(self, dropdown, _param) -> None:
        if self._syncing:
            return
        index = dropdown.get_selected()
        model = dropdown.get_model()
        if index == Gtk.INVALID_LIST_POSITION or model is None:
            return
        name = model.get_string(index)
        if name and name != self.cfg["device"]:
            self.cfg["device"] = name
            save_config(self.cfg)
            self.title_widget.set_subtitle(name)
            self.toast(f"Now controlling {name}")
            self._poll_device()

    # ---------- polling ----------

    def _poll_device(self) -> bool:
        if self.poll_busy:
            return True
        self.poll_busy = True
        device = self._device()
        Async.run(
            lambda: castctl.info(device),
            done=self._poll_done,
            failed=self._poll_failed,
        )
        return True

    def _poll_failed(self, _message) -> None:
        self.poll_busy = False

    def _poll_done(self, info) -> None:
        self.poll_busy = False
        previous = self.device_state
        self.device_info = info
        self.device_state = castctl.player_state(info)
        if info is None:
            self.device_state = "OFFLINE"
        self.tracker.set_state(self.device_state in {"PLAYING", "BUFFERING"})
        if self.session and info:
            # Sync the tracker with the device for BOTH direct and transcode
            # modes so the position pointer stays live and doesn't drift.
            # Use current_time whenever available (not just is_seekable) because
            # HLS streams report position but may not be seekable.
            current_time = info.get("current_time")
            duration = info.get("duration")
            if current_time is not None and duration is not None:
                self.tracker.device_update(float(current_time), float(duration))
        volume = castctl.volume_percent(info)
        if volume is not None and time.time() - self._volume_user_ts > 3:
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
        if previous != self.device_state:
            if self.device_state == "IDLE" and previous in {"PLAYING", "BUFFERING", "PAUSED"}:
                self._maybe_finished()
        self._refresh_controls()
        self._update_header_subtitle()

    def _detect_external(self) -> None:
        info = self.device_info
        idle = self.device_state in {"OFFLINE", "IDLE", "UNKNOWN"}
        if idle:
            if self.external:
                self.external = False
            if not self.session:
                self.now_playing = None
                self.tracker.clear()
            return
        if self.session and self.session.active():
            self.external = False
            return
        content = str((info or {}).get("content_id") or "")
        if f":{streamer.PORT}/" in content:
            return
        self.external = True
        self.tracker.clear()

    def _maybe_finished(self) -> None:
        if self._finished_handled:
            return
        if self.session and self.session.mode == "direct" and self.session.encoder_finished():
            self._finished_handled = True
            self._on_finished()

    def _on_finished(self) -> None:
        self._stop_monitor()
        self._set_levels_hint("")
        item = self.now_playing
        session, self.session = self.session, None
        if self.cfg["autonext"] and item in self.queue:
            index = self.queue.index(item)
            if index + 1 < len(self.queue):
                if session is not None:
                    device = self._device()
                    threading.Thread(target=lambda: session.stop(device, send_stop=False), daemon=True).start()
                self.now_playing = self.queue[index + 1]
                self.toast(f"Up next: {pathlib.Path(self.now_playing).name}")
                GLib.timeout_add(1200, lambda: (self._cast_path(pathlib.Path(self.now_playing), 0.0), False)[1])
                return
        if session is not None:
            device = self._device()
            threading.Thread(target=lambda: session.stop(device), daemon=True).start()
        self.tracker.clear()
        self.now_playing = None
        self.toast("Finished")
        self._rebuild_queue()
        self._refresh_controls()

    # ---------- ticking ----------

    def _tick(self) -> bool:
        session_active = bool(self.session and self.session.active())
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        position = self.tracker.value()
        buffered = None
        if self.session and self.session.mode == "transcode" and session_active:
            progress = self.session.progress()
            out_time = progress.get("out_time")
            if isinstance(out_time, (int, float)):
                buffered = out_time
            if (position is not None and duration and position >= duration - 0.6
                    and self.session.encoder_finished() and not self._finished_handled):
                self._finished_handled = True
                GLib.idle_add(self._on_finished)
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
        self._update_details()
        return True

    def _update_transport_icon(self) -> None:
        playing = self.device_state in {"PLAYING", "BUFFERING"}
        name = "media-playback-pause-symbolic" if playing else "media-playback-start-symbolic"
        if self._play_icon_name != name:
            self._play_icon_name = name
            self.play_image.set_from_icon_name(name)

    def _on_hover(self, hovering: bool, value: float) -> None:
        if hovering:
            self.elapsed_label.set_text(fmt_time(value))
            if self.tracker.duration:
                self.remaining_label.set_text(f"-{fmt_time(self.tracker.duration - value)}")
        else:
            position = self.tracker.value()
            if position is not None:
                self.elapsed_label.set_text(fmt_time(position))
                if self.tracker.duration:
                    self.remaining_label.set_text(f"-{fmt_time(self.tracker.duration - position)}")

    def _update_header_subtitle(self) -> None:
        labels = {
            "OFFLINE": "offline",
            "IDLE": "idle",
            "PLAYING": "playing",
            "BUFFERING": "buffering",
            "PAUSED": "paused",
        }
        state = labels.get(self.device_state, "idle")
        if self.external and state not in {"offline", "idle"}:
            state = "playing on TV"
        self.title_widget.set_subtitle(f"{self._device()} · {state}")

    def _set_chip(self, label: str, kind: str) -> None:
        for existing in ("idle", "playing", "paused", "buffering", "offline", "error"):
            self.state_chip.remove_css_class(existing)
        self.state_chip.add_css_class(kind)
        self.state_chip.set_text(label)

    def _set_now_playing_labels(self, media, session) -> None:
        title = pretty_title(media.path)
        meta = [media.resolution]
        if media.duration:
            meta.append(fmt_time(media.duration))
        if media.vcodec:
            meta.append(media.vcodec)
        if media.size_label:
            meta.append(media.size_label)
        if session is not None and session.state:
            meta.append("direct play" if session.mode == "direct" else "live transcode")
        text = " · ".join(bit for bit in meta if bit)
        if self.np_title.get_text() != title:
            self.np_title.set_text(title)
            self.np_title.set_tooltip_text(str(media.path))
        if self.np_meta.get_text() != text:
            self.np_meta.set_text(text)

    def _update_details(self) -> None:
        info = self.device_info
        session = self.session
        media = self.media
        state_text = {
            "OFFLINE": "Offline",
            "IDLE": "Idle",
            "PLAYING": "Playing",
            "BUFFERING": "Buffering",
            "PAUSED": "Paused",
        }.get(self.device_state, self.device_state.title())
        if self.external:
            state_text += " (external stream)"
        mode_text = "—"
        encoder_text = "—"
        if session and session.state:
            mode_text = "Direct play (buffered)" if session.mode == "direct" else "Live transcode (HLS)"
            if session.mode == "transcode":
                progress = session.progress()
                speed = progress.get("speed") or "—"
                fps = progress.get("fps") or "—"
                engine = "libx264 (CPU)" if session.used_software_fallback else "h264 VAAPI"
                encoder_text = f"{engine} · {speed} · {fps} fps"
            else:
                encoder_text = "device-native"
        if self.external and info:
            title = f"{str(info.get('title') or 'external stream')} · external"
            if self.np_title.get_text() != title:
                self.np_title.set_text(title)
            hint = "Another app started this stream — controls are limited"
            if self.np_meta.get_text() != hint:
                self.np_meta.set_text(hint)
        position = self.tracker.value()
        position_text = "unknown" if position is None else f"{fmt_time(position)} of {fmt_time(self.tracker.duration)}"
        if self.tracker.known and session and session.mode == "transcode":
            position_text += " (estimated)"
        subtitle_text = "—"
        if session and session.state:
            if session.state.subs:
                subtitle_text = pathlib.Path(session.state.subs).name + (" (burned in)" if session.state.burn_subs else "")
            else:
                subtitle_text = "off"
        elif self._active_subs():
            subtitle_text = pathlib.Path(self._active_subs()).name + " (ready)"
        else:
            subtitle_text = "off"
        url_text = session.state.stream_url if session and session.state and session.state.stream_url else "—"
        media_text = "—"
        if media:
            bits = [media.resolution, media.vcodec, media.pix_fmt]
            if media.size_label:
                bits.append(media.size_label)
            media_text = " · ".join(bit for bit in bits if bit)
        audio_text = "—"
        if media:
            parts = [media.acodec or "unknown audio"]
            if media.channels:
                parts.append(f"{media.channels}ch")
            if media.audio_tracks > 1:
                parts.append(f"{media.audio_tracks} tracks")
            audio_text = " · ".join(parts)
        file_text = pathlib.Path(session.state.file).name if session and session.state else (
            pathlib.Path(self.now_playing).name if self.now_playing else "—"
        )
        values = {
            "state": state_text,
            "mode": mode_text,
            "encoder": encoder_text,
            "position": position_text,
            "resolution": media_text,
            "audio": audio_text,
            "subs": subtitle_text,
            "file": file_text,
            "url": url_text,
        }
        for key, value in values.items():
            label = self.detail_labels.get(key)
            if label is not None and label.get_text() != value:
                label.set_text(value)
                if key in ("file", "url"):
                    label.set_tooltip_text(value if value != "—" else None)
        url_available = bool(url_text and url_text != "—")
        if self.copy_url_button.get_visible() != url_available:
            self.copy_url_button.set_visible(url_available)
        if media is not None and not (session and session.state):
            self._set_now_playing_labels(media, None)
        self.subs_detail.set_text(self._subs_status_text())

    def _subs_status_text(self) -> str:
        mode = self.cfg["subs"]
        if mode == "off":
            return "Subtitles off"
        if mode == "pick":
            path = self.cfg["subs_path"]
            return f"Using {pathlib.Path(path).name}" if path else "No subtitle file picked yet"
        if self.now_playing:
            found = self._cached_subs(self.now_playing)
            if found:
                return f"Found next to video: {pathlib.Path(found).name}"
            return "No matching subtitle file next to the video"
        return "Matches .srt/.vtt files named after the video"

    def _cached_subs(self, path: str) -> str | None:
        cached_path, cached_result = self._subs_cache
        if cached_path == path:
            return cached_result
        found = streamer.find_subtitles(pathlib.Path(path))
        result = str(found) if found else None
        self._subs_cache = (path, result)
        return result

    # ---------- controls state ----------

    def _refresh_controls(self) -> None:
        online = self.device_state != "OFFLINE"
        playing = self.device_state in {"PLAYING", "BUFFERING"}
        paused = self.device_state == "PAUSED"
        busy = self.busy
        active = (self.session is not None and self.session.active()) or self.external
        self.cast_button.set_sensitive(not busy)
        can_play = online and not busy and (active or self.now_playing is not None or self.selected_index is not None)
        self.play_button.set_sensitive(can_play)
        self.stop_button.set_sensitive(online and not busy and active)
        can_seek = online and not busy and not self.external and self.tracker.known and active
        for button in (self.back10_button, self.back30_button, self.fwd10_button, self.fwd30_button):
            button.set_sensitive(can_seek)
        has_queue = bool(self.queue)
        index = self.queue.index(self.now_playing) if self.now_playing in self.queue else None
        self.prev_button.set_sensitive(not busy and (has_queue and (index is None or index > 0) or active))
        self.next_button.set_sensitive(not busy and has_queue and index is not None and index + 1 < len(self.queue))
        self.volume_scale.set_sensitive(online)
        self.mute_button.set_sensitive(online)
        self.cc_button.set_sensitive(active and not busy)
        has_subs = bool(self._active_subs()) or bool(self.session and self.session.state and self.session.state.subs)
        self._syncing = True
        self.cc_button.set_active(has_subs and self.cfg["subs"] != "off")
        self._syncing = False
        if self.device_state == "OFFLINE":
            self._set_chip("Offline", "offline")
        elif self.busy:
            self._set_chip("Preparing…", "buffering")
        elif self.external:
            self._set_chip("External", "paused")
        elif self.device_state == "BUFFERING":
            self._set_chip("Buffering…", "buffering")
        elif playing:
            self._set_chip("Live" if (self.session and self.session.mode == "transcode") else "Playing", "playing")
        elif paused:
            self._set_chip("Paused", "paused")
        else:
            self._set_chip("Ready", "idle")

    def _nudge_volume(self, delta: int) -> None:
        self.volume_scale.set_value(max(0, min(100, self.volume_scale.get_value() + delta)))

    # ---------- volume ----------

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

    def _on_volume_changed(self, scale) -> None:
        value = int(scale.get_value())
        self.volume_label.set_text(f"{value}%")
        self._apply_volume_icon()
        if self._syncing:
            return
        self._volume_user_ts = time.time()
        if self._volume_job is not None:
            GLib.source_remove(self._volume_job)
        self._volume_job = GLib.timeout_add(300, self._commit_volume)

    def _commit_volume(self) -> bool:
        self._volume_job = None
        if self.device_state == "OFFLINE":
            return False
        value = int(self.volume_scale.get_value())
        device = self._device()
        Async.run(lambda: castctl.volume(device, value))
        return False

    def _on_mute(self, button) -> None:
        if self._syncing:
            return
        muted = button.get_active()
        self._apply_volume_icon()
        if self.device_state == "OFFLINE":
            return
        device = self._device()
        Async.run(lambda: castctl.set_muted(device, muted))
        self.toast("Muted" if muted else "Sound on")

    def toggle_mute(self) -> None:
        self.mute_button.set_active(not self.mute_button.get_active())

    # ---------- transport ----------

    def toggle_play(self) -> None:
        if self.device_state == "OFFLINE" or self.busy:
            if self.device_state == "OFFLINE":
                self.toast("Device is offline", error=True)
            return
        if not (self.session and self.session.active()) and not self.external and self.now_playing is None:
            self.cast_selected()
            return
        device = self._device()
        want_play = self.device_state not in {"PLAYING", "BUFFERING"}
        self.tracker.set_state(want_play)

        def work():
            if want_play:
                return castctl.play(device)
            return castctl.pause(device)

        def done(result):
            ok, message = result
            if not ok:
                self.toast(message or "Command failed", error=True)
            if want_play:
                self._resume_monitor()
            else:
                self._stop_monitor(reset=False)
            self._poll_device()

        Async.run(work, done=done)

    def stop_stream(self) -> None:
        if self.busy:
            return
        self.busy = True
        self._refresh_controls()
        device = self._device()
        session = self.session
        self.session = None

        def work():
            if session is not None:
                session.stop(device)
            else:
                castctl.stop(device)

        def done(_result):
            self.busy = False
            self.tracker.clear()
            self.now_playing = None
            self._finished_handled = False
            self._stop_monitor()
            self._set_levels_hint("")
            self.toast("Stopped")
            self._rebuild_queue()
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=lambda msg: self._cast_failed(msg))

    def _current_media(self) -> streamer.MediaInfo | None:
        if self.media is not None and self.now_playing is not None and str(self.media.path) == self.now_playing:
            return self.media
        return None

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
        self._cast_path(pathlib.Path(path), 0.0)

    def _cast_path(self, path: pathlib.Path, offset: float) -> None:
        if self.busy:
            self.toast("Hold on — finishing the last command")
            return
        self.busy = True
        self._refresh_controls()
        self._finished_handled = False
        device = self._device()
        cfg = self.cfg
        previous = self.session
        subs_mode = cfg["subs"]
        subs_path = self._resolve_subs(path)
        burn = bool(cfg["burn_subs"]) and subs_path is not None
        # Direct play hands the file to the TV untouched, so it can only be used
        # when no audio processing is wanted. Any dialogue/night profile needs
        # the transcode pipeline to apply its filters.
        use_direct = bool(cfg["direct"]) and cfg["audio"] == "original"

        def work():
            media = streamer.ffprobe(path)
            if previous is not None:
                previous.stop(device, send_stop=False)
            session = streamer.Session()
            title = pretty_title(path)
            if use_direct and media.direct_ok and not burn:
                try:
                    session.start_direct(
                        media, device=device, subs_file=subs_path,
                        subs_disabled=(subs_mode == "off"), title=title,
                    )
                    return session, media
                except streamer.StreamError:
                    session = streamer.Session()
            session.start_transcode(
                media, offset, device=device, quality=cfg["quality"],
                audio_profile=cfg["audio"], subs_file=subs_path,
                burn_subs=burn, title=title,
                audio_gain_db=float(cfg.get("audio_gain", DEFAULTS["audio_gain"])),
            )
            return session, media

        def done(result):
            session, media = result
            self.session = session
            self.media = media
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
                hint = "Original audio (direct play)"
            self._start_monitor(media.path, started, chain)
            self._set_levels_hint(hint)
            self.tracker.start(started, media.duration, True)
            self._add_recent(str(path))
            self._set_now_playing_labels(media, session)
            self.toast(f"Casting {pretty_title(path)} to {device}")
            self._rebuild_queue()
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=self._cast_failed)
        self.np_title.set_text(path.name)

    def _cast_failed(self, message: str) -> None:
        self.busy = False
        self._stop_monitor()
        self._set_levels_hint("")
        if self.session is not None and not self.session.active():
            self.session = None
        if self.session is None:
            self.tracker.clear()
            self._finished_handled = False
        self.toast(f"Cast failed: {message}", error=True)
        self._refresh_controls()

    def _resolve_subs(self, video: pathlib.Path) -> pathlib.Path | None:
        mode = self.cfg["subs"]
        if mode == "off":
            return None
        if mode == "pick":
            path = pathlib.Path(self.cfg["subs_path"]).expanduser()
            return path if path.is_file() else None
        return streamer.find_subtitles(video)

    def _active_subs(self) -> str | None:
        mode = self.cfg["subs"]
        if mode == "off" or self.now_playing is None:
            return None
        if mode == "pick":
            path = pathlib.Path(self.cfg["subs_path"]).expanduser()
            return str(path) if path.is_file() else None
        return self._cached_subs(self.now_playing)

    def seek_to(self, target: float) -> None:
        target = max(0.0, target)
        duration = self.tracker.duration or (self.media.duration if self.media else 0.0)
        if duration:
            target = min(target, max(0.0, duration - 1.0))
        if self.external:
            self.toast("The position of an external stream is unknown", error=True)
            return
        session = self.session
        if session is None or not session.active():
            if self.now_playing:
                self._cast_path(pathlib.Path(self.now_playing), target)
            else:
                self.toast("Nothing is playing yet")
            return
        if session.mode == "direct" and castctl.is_seekable(self.device_info):
            device = self._device()
            self.tracker.device_update(target, duration)

            def done(result):
                ok, message = result
                if not ok:
                    self.toast(message or "Seek failed", error=True)
                self._poll_device()

            Async.run(lambda: castctl.seek(device, target), done=done)
            self.toast(f"Jumped to {fmt_time(target)}")
            return
        if self.busy:
            self.toast("Hold on — finishing the last command")
            return
        self.busy = True
        self._refresh_controls()
        self.toast(f"Restarting stream at {fmt_time(target)}…")
        self._restart_at(session, target)

    def _restart_at(self, session, target: float) -> None:
        device = self._device()
        state = session.state
        file_path = pathlib.Path(state.file) if state else None
        title = state.title if state else (file_path.stem if file_path else "video")
        quality = state.quality if state else self.cfg["quality"]
        audio = state.audio if state else self.cfg["audio"]
        burn = bool(state.burn_subs) if state else False
        subs_path = None
        if state and state.subs:
            candidate = pathlib.Path(state.subs)
            subs_path = candidate if candidate.is_file() else None
        media = self.media if (self.media and file_path and self.media.path == file_path) else None

        def work():
            nonlocal media
            if media is None:
                media = streamer.ffprobe(file_path)
            session.stop(device, send_stop=False)
            session.start_transcode(
                media, target, device=device, quality=quality,
                audio_profile=audio, subs_file=subs_path, burn_subs=burn, title=title,
                audio_gain_db=float(self.cfg.get("audio_gain", DEFAULTS["audio_gain"])),
            )
            return session, media

        def done(result):
            _session, media_result = result
            self.media = media_result
            self.busy = False
            gain = _session.state.audio_gain_db if _session.state else 0.0
            chain = streamer.audio_filters(audio, gain)
            self._start_monitor(media_result.path, target, chain)
            hint = streamer.AUDIO_LABELS.get(audio, audio)
            if gain > 0:
                hint += f" · +{gain:g} dB"
            self._set_levels_hint(hint)
            self.tracker.start(target, media_result.duration, True)
            self._refresh_controls()
            self._poll_device()

        Async.run(work, done=done, failed=self._cast_failed)

    def _skip_back10(self) -> None:
        self._skip(-10)

    def _skip_forward10(self) -> None:
        self._skip(10)

    def _skip_back30(self) -> None:
        self._skip(-30)

    def _skip_forward30(self) -> None:
        self._skip(30)

    def _skip(self, delta: float) -> None:
        position = self.tracker.value()
        if position is None:
            self.toast("Position unknown — nothing to skip in")
            return
        self.seek_to(position + delta)

    def on_prev(self) -> None:
        if self.now_playing in self.queue:
            index = self.queue.index(self.now_playing)
            if index > 0:
                self.now_playing = self.queue[index - 1]
                self._cast_path(pathlib.Path(self.now_playing), 0.0)
                return
        if self.now_playing:
            self.seek_to(0.0)

    def on_next(self) -> None:
        if self.now_playing in self.queue:
            index = self.queue.index(self.now_playing)
            if index + 1 < len(self.queue):
                self.now_playing = self.queue[index + 1]
                self._cast_path(pathlib.Path(self.now_playing), 0.0)

    # ---------- queue ----------

    def _rebuild_queue(self) -> None:
        while self.queue_list.get_row_at_index(0) is not None:
            self.queue_list.remove(self.queue_list.get_row_at_index(0))
        for index, path in enumerate(self.queue):
            self.queue_list.append(self._queue_row(index, path))
        self.queue_empty.set_visible(not self.queue)
        self.queue_list.set_visible(bool(self.queue))
        if (self.selected_index is not None and 0 <= self.selected_index < len(self.queue)):
            row = self.queue_list.get_row_at_index(self.selected_index)
            if row is not None:
                self.queue_list.select_row(row)
        self.queue_summary.set_visible(bool(self.queue))
        if self.queue:
            total = sum(self.queue_durations.get(p, 0.0) or 0.0 for p in self.queue)
            known = all(self.queue_durations.get(p) for p in self.queue)
            text = f"{len(self.queue)} video{'s' if len(self.queue) != 1 else ''}"
            if total > 0:
                text += f" · {fmt_time(total)}{'' if known else '+'}"
            self.queue_summary.set_text(text)
        self._refresh_controls()

    def _queue_row(self, index: int, path: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("queue-row")
        if path == self.now_playing:
            row.add_css_class("current")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        index_label = Gtk.Label(label=str(index + 1))
        index_label.add_css_class("dim-label")
        index_label.add_css_class("caption")
        index_label.set_width_chars(2)
        title = Gtk.Label(label=pathlib.Path(path).name, xalign=0.0, hexpand=True, ellipsize=3)
        title.add_css_class("queue-title")
        title.set_tooltip_text(path)
        duration = self.queue_durations.get(path)
        duration_label = Gtk.Label(label=fmt_time(duration) if duration else "")
        duration_label.add_css_class("dim-label")
        duration_label.add_css_class("caption")
        up = self._icon_button("go-up-symbolic", "Move up", "flat", lambda i=index: self._move_queue(i, -1))
        down = self._icon_button("go-down-symbolic", "Move down", "flat", lambda i=index: self._move_queue(i, 1))
        remove = self._icon_button("window-close-symbolic", "Remove", "flat", lambda i=index: self._remove_queue(i))
        up.set_sensitive(index > 0)
        down.set_sensitive(index + 1 < len(self.queue))
        for widget in (index_label, title, duration_label, up, down, remove):
            box.append(widget)
        row.set_child(box)
        return row

    def _on_queue_activated(self, _list, row) -> None:
        index = row.get_index()
        if index < len(self.queue):
            self.now_playing = self.queue[index]
            self._cast_path(pathlib.Path(self.now_playing), 0.0)

    def _on_queue_selected(self, _list, row) -> None:
        self.selected_index = row.get_index() if row is not None else None

    def _move_queue(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= target < len(self.queue):
            self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
            self._rebuild_queue()

    def _remove_queue(self, index: int) -> None:
        if index < len(self.queue):
            removed = self.queue.pop(index)
            if removed == self.now_playing and not (self.session and self.session.active()):
                self.now_playing = None
            self._rebuild_queue()

    def clear_queue(self) -> None:
        self.queue.clear()
        self.selected_index = None
        self._rebuild_queue()
        self.toast("Queue cleared")

    def add_files(self) -> None:
        dialog = Gtk.FileDialog(title="Add videos to the queue")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video files")
        for pattern in ("*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm", "*.m4v", "*.ts", "*.mpeg", "*.mpg", "*.wmv"):
            video_filter.add_pattern(pattern)
        store.append(video_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        store.append(all_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(video_filter)
        dialog.open_multiple(self, None, self._files_chosen)

    def _files_chosen(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        paths = []
        for index in range(files.get_n_items()):
            gfile = files.get_item(index)
            path = gfile.get_path()
            if path:
                paths.append(path)
        self._enqueue(paths)

    def _enqueue(self, paths: list[str]) -> None:
        added = 0
        for path in paths:
            if path not in self.queue:
                self.queue.append(path)
                added += 1
        if not added:
            return
        self._rebuild_queue()
        self.toast(f"Added {added} video{'s' if added != 1 else ''} to the queue")
        if self.now_playing is None and self.selected_index is None and self.queue:
            self.set_selection(self.queue[0])

        def probe():
            for path in paths:
                if path in self.queue_durations:
                    continue
                try:
                    media = streamer.ffprobe(pathlib.Path(path))
                    self.queue_durations[path] = media.duration
                except Exception:
                    self.queue_durations[path] = 0.0
            return True

        Async.run(probe, done=lambda _r: self._rebuild_queue())

    def open_video(self) -> None:
        dialog = Gtk.FileDialog(title="Choose a video")
        store = Gio.ListStore.new(Gtk.FileFilter)
        video_filter = Gtk.FileFilter()
        video_filter.set_name("Video files")
        for pattern in ("*.mp4", "*.mkv", "*.mov", "*.avi", "*.webm", "*.m4v", "*.ts", "*.mpeg", "*.mpg", "*.wmv"):
            video_filter.add_pattern(pattern)
        store.append(video_filter)
        dialog.set_filters(store)
        dialog.set_default_filter(video_filter)
        dialog.open(self, None, self._file_chosen)

    def _file_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            self.set_selection(path)
            self._cast_path(pathlib.Path(path), 0.0)

    def set_selection(self, path: str) -> None:
        if path not in self.queue:
            self.queue.append(path)
            self._rebuild_queue()
        index = self.queue.index(path)
        self.selected_index = index
        row = self.queue_list.get_row_at_index(index)
        if row is not None:
            self.queue_list.select_row(row)
        if self.now_playing is None:
            self.np_title.set_text(pathlib.Path(path).name)
        if self.session is None:
            self.media = None

        def work():
            return path, streamer.ffprobe(pathlib.Path(path))

        def done(result):
            path_result, media = result
            self.queue_durations[path_result] = media.duration
            if self.now_playing is None and self.session is None:
                self.media = media
            self._rebuild_queue()

        Async.run(work, done=done)
        self._refresh_controls()

    def open_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        first = paths[0]
        self.set_selection(first)
        if len(paths) > 1:
            self._enqueue(paths[1:])
        self.present()

    # ---------- subs ----------

    def _on_cc_toggled(self, button) -> None:
        if self.busy or self._syncing:
            return
        on = button.get_active()
        device = self._device()

        def work():
            return castctl.subs_on(device) if on else castctl.subs_off(device)

        def done(result):
            ok, message = result
            self.toast("Captions on" if on and ok else ("Captions off" if ok else (message or "Caption toggle failed")))

        Async.run(work, done=done)

    # ---------- settings callbacks ----------

    def _on_quality(self, dropdown, _param) -> None:
        if self._syncing:
            return
        mapping = {0: "high", 1: "balanced", 2: "saver"}
        value = mapping.get(dropdown.get_selected(), "balanced")
        if value != self.cfg["quality"]:
            self.cfg["quality"] = value
            save_config(self.cfg)
            self.toast(f"Quality: {streamer.QUALITY_LABELS[value]} (restart to apply)")

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

    def _refresh_direct_note(self) -> None:
        switch = getattr(self, "direct_switch", None)
        label = getattr(switch, "subtitle_label", None) if switch is not None else None
        if label is None:
            return
        if self.cfg["direct"] and self.cfg["audio"] != "original":
            label.set_text("Ignored while a sound enhancement is selected — the "
                           "enhancer needs the transcode pipeline")
        else:
            label.set_text("Instant seeking for H.264/AAC files")

    def _on_gain(self, spin) -> None:
        if self._syncing:
            return
        value = int(round(float(spin.get_value())))
        value = max(0, min(24, value))
        if value != self.cfg.get("audio_gain"):
            self.cfg["audio_gain"] = float(value)
            save_config(self.cfg)

    def _on_subs_mode(self, dropdown, _param) -> None:
        if self._syncing:
            return
        mapping = {0: "off", 1: "auto", 2: "pick"}
        value = mapping.get(dropdown.get_selected(), "auto")
        if value == "pick":
            dialog = Gtk.FileDialog(title="Choose a subtitle file")
            sub_filter = Gtk.FileFilter()
            sub_filter.set_name("Subtitles")
            for pattern in ("*.srt", "*.vtt", "*.ttml", "*.ass"):
                sub_filter.add_pattern(pattern)
            store = Gio.ListStore.new(Gtk.FileFilter)
            store.append(sub_filter)
            dialog.set_filters(store)
            dialog.open(self, None, self._subs_file_chosen)
            return
        self.cfg["subs"] = value
        save_config(self.cfg)
        self.toast("Subtitles: " + {"off": "off", "auto": "auto"}[value])

    def _subs_file_chosen(self, dialog, result) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            self.subs_dropdown.set_selected(1)
            return
        path = gfile.get_path()
        if path:
            self.cfg["subs"] = "pick"
            self.cfg["subs_path"] = path
            save_config(self.cfg)
            self.toast(f"Subtitles: {pathlib.Path(path).name}")

    def _on_burn(self, switch, _param) -> None:
        self.cfg["burn_subs"] = switch.get_active()
        save_config(self.cfg)
        if switch.get_active():
            self.toast("Subtitles will be burned in (slower encode)")

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

    # ---------- recents ----------

    def _add_recent(self, path: str) -> None:
        recents = [p for p in self.cfg["recents"] if p != path]
        recents.insert(0, path)
        self.cfg["recents"] = recents[:8]
        save_config(self.cfg)
        self.menu_button.set_menu_model(self._build_menu())

    def open_recent(self, index: int) -> None:
        recents = self.cfg["recents"]
        if 0 <= index < len(recents):
            path = pathlib.Path(recents[index])
            if path.is_file():
                self.set_selection(str(path))
                self._cast_path(path, 0.0)
            else:
                self.toast("That file has moved or been deleted", error=True)

    # ---------- adoption ----------

    def _adopt_session(self) -> bool:
        state = streamer.load_session()
        if state is None:
            return False
        session = streamer.Session()
        session.restore(state)
        if not session.active():
            streamer.clear_session()
            return False
        self.session = session
        self.now_playing = state.file
        if state.file not in self.queue:
            self.queue.append(state.file)
            self._rebuild_queue()
        device = self._device()
        # Immediate best estimate so the seek bar is not stuck at 0 while the
        # accurate device position is fetched. Works for direct and transcode.
        elapsed = max(0.0, time.time() - state.started_at) if state.started_at else 0.0
        self.tracker.start(min(state.offset + elapsed, state.duration or 1e18), state.duration, True)
        self.toast(f"Reconnected to {pathlib.Path(state.file).name}")

        def probe():
            media = streamer.ffprobe(pathlib.Path(state.file))
            current = 0.0
            try:
                info = castctl.info(device)
                if info:
                    current = float(info.get("current_time") or 0.0)
            except Exception:
                current = 0.0
            return media, current

        def probed(result):
            media, current = result
            self.media = media
            if current > 0:
                self.tracker.start(min(current, media.duration or current), media.duration, True)
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

        Async.run(probe, done=probed, failed=lambda _msg: None)
        self._refresh_controls()
        self._poll_device()
        return False

    # ---------- lifecycle ----------

    def _on_close(self, _window) -> bool:
        self._stop_monitor()
        self.cfg["window_width"] = self.get_width()
        self.cfg["window_height"] = self.get_height()
        save_config(self.cfg)
        if not self.cfg["keep_streaming"] and self.session is not None:
            session, self.session = self.session, None
            device = self._device()
            thread = threading.Thread(target=lambda: session.stop(device), daemon=False)
            thread.start()
        return False

    # ---------- app actions ----------

    def action_open(self, *_args) -> None:
        self.open_video()

    def action_add_files(self, *_args) -> None:
        self.add_files()

    def action_stop(self, *_args) -> None:
        self.stop_stream()

    def action_shortcuts(self, *_args) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("Keyboard shortcuts")
        dialog.set_content_width(420)
        dialog.set_content_height(520)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        shortcuts = [
            ("Space", "Play or pause"),
            ("K", "Play or pause"),
            ("Left", "Skip back 10 seconds"),
            ("Right", "Skip forward 10 seconds"),
            ("<Shift>Left", "Skip back 30 seconds"),
            ("<Shift>Right", "Skip forward 30 seconds"),
            ("J", "Skip back 10 seconds"),
            ("L", "Skip forward 10 seconds"),
            ("Up", "Volume up 5%"),
            ("Down", "Volume down 5%"),
            ("M", "Mute"),
            ("S", "Stop the stream"),
            ("P", "Previous in queue"),
            ("N", "Next in queue"),
            ("<Control>o", "Open a video"),
            ("<Control>a", "Add videos to queue"),
        ]
        for accel, title in shortcuts:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            label = Gtk.Label(label=title, xalign=0.0, hexpand=True)
            shortcut_label = Gtk.ShortcutLabel(accelerator=accel)
            row.append(label)
            row.append(shortcut_label)
            box.append(row)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        label = Gtk.Label(label="Jump to 10% – 90%", xalign=0.0, hexpand=True)
        chips = Gtk.Label(label="1 – 9")
        chips.add_css_class("dim-label")
        row.append(label)
        row.append(chips)
        box.append(row)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(box)
        toolbar.set_content(scroller)
        dialog.set_child(toolbar)
        dialog.present(self)

    def action_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=ICON_NAME,
            version="2.0",
            developer_name="gridout",
            comments="A modern companion for casting local videos to a Chromecast: live HLS transcoding or direct play, queue, captions, sound profiles and full remote control.",
        )
        about.present(self)

    def perform_action(self, name: str) -> None:
        if name == "open":
            self.action_open()
        elif name == "add":
            self.action_add_files()
        elif name == "stop":
            self.action_stop()
        elif name == "shortcuts":
            self.action_shortcuts()


class CastControlApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.window: MainWindow | None = None
        self.selftest = False
        self._pending_files: list[str] = []

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        GLib.set_prgname(APP_ID)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._register_actions()
        self.set_accels_for_action("app.open", ["<Control>o"])
        self.set_accels_for_action("app.add-files", ["<Control>a"])
        self.set_accels_for_action("app.shortcuts", ["<Control>question"])
        self.set_accels_for_action("app.stop-stream", ["<Control>w"])
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _register_actions(self) -> None:
        def simple(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        simple("open", lambda *a: self._window().action_open())
        simple("add-files", lambda *a: self._window().action_add_files())
        simple("stop-stream", lambda *a: self._window().action_stop())
        simple("shortcuts", lambda *a: self._window().action_shortcuts())
        simple("about", lambda *a: self._window().action_about())
        simple("quit", lambda *a: self.quit())
        for index in range(8):
            action = Gio.SimpleAction.new(f"recent-{index}", None)
            action.connect("activate", lambda _a, _p, i=index: self._window().open_recent(i))
            self.add_action(action)
        scheme = Gio.SimpleAction.new_stateful(
            "color-scheme", GLib.VariantType.new("s"), GLib.Variant("s", "prefer-dark")
        )
        scheme.connect("activate", self._activate_scheme)
        self.add_action(scheme)
        self.scheme_action = scheme

    def _activate_scheme(self, action, parameter) -> None:
        value = parameter.get_string()
        action.set_state(GLib.Variant("s", value))
        window = self.window
        if window is not None:
            window.cfg["color_scheme"] = value
            save_config(window.cfg)
            window._apply_color_scheme()

    def _window(self) -> MainWindow:
        window = self.window
        if window is None:
            window = MainWindow(self)
            self.window = window
            self.scheme_action.set_state(GLib.Variant("s", window.cfg["color_scheme"]))
        return window

    def do_activate(self) -> None:
        window = self._window()
        window.present()
        if self._pending_files:
            window.open_paths(self._pending_files)
            self._pending_files = []
        if self.selftest:
            GLib.timeout_add(6500, self._selftest_quit)

    def _selftest_quit(self) -> bool:
        print("SELFTEST: window built successfully")
        self.quit()
        return False

    def do_open(self, files, n_files, _hint) -> None:
        paths = []
        for index in range(n_files):
            path = files[index].get_path()
            if path:
                paths.append(path)
        window = self._window()
        window.present()
        if paths:
            window.open_paths(paths)

    def do_command_line(self, command_line) -> int:
        raw = command_line.get_arguments()[1:]
        action = None
        paths: list[str] = []
        index = 0
        while index < len(raw):
            argument = raw[index]
            if argument == "--action" and index + 1 < len(raw):
                action = raw[index + 1]
                index += 2
                continue
            if argument.startswith("file://"):
                path = GLib.filename_from_uri(argument)[0]
                if path:
                    paths.append(path)
            elif argument and not argument.startswith("-"):
                candidate = pathlib.Path(argument).expanduser()
                if candidate.is_file():
                    paths.append(str(candidate.resolve()))
            index += 1
        self.activate()
        window = self._window()
        window.present()
        if paths:
            window.open_paths(paths)
        if action:
            GLib.timeout_add(250, lambda: (window.perform_action(action), False)[1])
        return 0


def main() -> int:
    selftest = "--self-test" in sys.argv
    argv = [arg for arg in sys.argv if arg != "--self-test"]
    app = CastControlApp()
    app.selftest = selftest
    result = app.run(argv)
    if selftest and result == 0:
        print("SELFTEST OK")
    return result


if __name__ == "__main__":
    sys.exit(main())
