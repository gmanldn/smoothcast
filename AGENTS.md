# AGENTS.md — SmoothCast

## Critical rules (read first)
- **Commit after every meaningful change.** User loses work if not committed. Run `git add -A && git commit -m "..."` frequently.
- **Commit at least every ~10,000 lines of code or so**, even if the change is small, so work is never lost.
- Never ask the user for confirmation to commit — just do it.
- **Version counter:** `src/version.py` holds `__version__` = `1.0.x`. Increment the patch number (`x`) on **every single commit**. This makes every build traceable to a specific commit.
- Keep responses short and technical. No preamble, no postamble.

## Project
SmoothCast is a GTK4/libadwaita Chromecast companion app.
- Launcher: `./smoothcast` (creates `.venv`, installs catt, runs `src/cast_control.py`; GUI starts repair the user-level desktop launcher and themed icon). `./sc.py` is an executable alias that forwards arguments; repeat starts raise the existing GTK window, not kill/restart a cast.
- Run directly: `DISPLAY=:99 .venv/bin/python src/cast_control.py`
- Self-test: `.venv/bin/python src/cast_control.py --self-test`

## Display / screenshots
- Use `Xvfb :99 -screen 0 1280x800x24 -ac` for virtual display.
- Capture window by ID with Xlib + PIL:
  ```python
  from Xlib import X, display
  from PIL import Image
  d = display.Display(':99')
  window = d.create_resource_object('window', WINDOW_ID)
  wgeom = window.get_geometry()
  image = window.get_image(wgeom.x, wgeom.y, wgeom.width, wgeom.height, X.ZPixmap, 0xffffffff)
  img = Image.frombytes('RGB', (wgeom.width, wgeom.height), image.data, 'raw', 'BGRX')
  img.save('/tmp/app.png')
  ```
- Find window ID: `DISPLAY=:99 xdotool search --all --name ""`

## Key files
- `src/cast_control.py` — main GTK app, LevelMeter widget, MainWindow, version import
- `src/audio_monitor.py` — fast ffmpeg analysis of input/output levels
- `src/streamer.py` — HLS transcode, direct play, ffmpeg chains, audio filters
- `src/castctl.py` — catt CLI wrapper
- `src/server.py` — HLS static file server / allowlisted HLS HTTP server (playlist, TS segments, health probe only; never serve session.json or logs)
- `src/error_log.py` — ring-buffer error log (errors.log, 10k lines, gitignored)
- `src/position_tracker.py` — playback position estimation (no GTK dep)
- `src/responsive_layout.py` — GTK-free screen bounds and responsive breakpoints
- `src/utils.py` — pure text helpers (pretty_title)
- `src/version.py` — version counter (MAJOR.MINOR.PATCH)
- `src/url_control.py` — HTTP(S) URL validation for remote casting
- `src/screenshot.py` — bounded, collision-safe FFmpeg capture worker
- `src/playback_state.py` — testable queue, timing and sleep-deadline decisions
- `tests/` — pytest suite (runs without GTK/display)
- `pytest.ini` — pytest config (testpaths, pythonpath=src)

## Architecture
- GTK4 + libadwaita UI runs on the main thread via `Adw.Application`.
- All blocking I/O (castctl, ffmpeg, network) runs in background threads via `Async.run()` and is marshalled back to the main thread with `GLib.idle_add()`. The main thread never blocks — the UI stays responsive at all times.
- The compressor (`acompressor` + `alimiter`) lives in `streamer.py:AUDIO_FILTERS` and is applied **only** in the ffmpeg transcode chain that produces the HLS stream sent to the Chromecast. It does **not** affect local machine audio, the original file, or any other application.
- The audio monitor (`audio_monitor.py`) runs a separate read-only ffmpeg pass for metering; it never touches playback.
- UI responsiveness: The `_tick` method runs every 500ms and does only lightweight UI updates (seekbar, labels, details). The `_meter_tick` runs every 100ms and does only lightweight meter drawing. No blocking work runs on the main thread.
- Auto-update on launch: `src/update_control.py` runs `git pull --ff-only` once in a background thread after the first GTK window is visible. It skips release archives and self-tests. Updated code takes effect on the next launch; a toast asks the user to restart after playback. The network must never delay startup.
- Single-instance activation is handled by GApplication/D-Bus: a second dock launch forwards activation to the existing window and presents it. Never reintroduce a PID/file lock before `app.run()`.
- Graceful error handling: `main()` wraps `app.run()` in try/except.

## Testing (portable, GTK-free)
- Run: `python3 -m pytest` (from repo root) — no display needed.
- Logic modules (`position_tracker`, `utils`, `castctl`, `audio_monitor`, `streamer`, `error_log`) import without GTK — safe on CI.
- GTK UI (`cast_control.py`) is covered by the self-test which builds the full window: `DISPLAY=:99 .venv/bin/python src/cast_control.py --self-test`.
- All modules must `compileall` clean; self-test must print `SELFTEST OK`.

## Error log
- Uncaught exceptions (main + background threads) and `Async.run` failures are appended to `errors.log` (ring buffer, max 10,000 lines, gitignored).
- Path: `~/.config/cast-control/errors.log`.

## Version
- `src/version.py`: `__version__ = "1.0.x"` — increment `PATCH` on every commit.
- Current: `1.0.38`
- Release tags mark releases, e.g. `v1.0.37`. Bump via `git tag v<major>.<minor>.<patch>` and push tags with `--tags`.

## UI features
- Preview screen above scrubbing bar: `PreviewScreen` widget shows video title/info as a colored placeholder.
- Scrubbing knob moves immediately on seek/jump: `seek_to()` updates the seekbar directly, and `tracker.device_update()` is called immediately for both direct and transcode modes so `_tick()` doesn't override the knob while the cast catches up.
- Casting status in details card: Buffer Health (ahead/behind time) and Segments (HLS segment count) rows show exact cast status.
- Error handling: `main()` wraps `app.run()` in try/except; GApplication handles repeat activation.
- Modern CSS styling: explicit dark slate theme (#0e0e10 bg, #4f8cff accent) with refined cards, hover states on all buttons, larger transport controls (80px play button), improved seekbar with accent-colored knob, better typography hierarchy with uppercase headings, generous margins and card spacing.
- Responsive layout: paned split resizes both children, right panel is scrollable and flexible, minimum window 1200x800 with default 1400x900, no fixed widths preventing scaling.
- Version number shown on front page: header subtitle displays `device · vX.Y.Z`.

## Completed work
1. Compressor only affects playback (verified by code inspection).
2. Bouncing master line meter added to `LevelMeter` — shows post-compressor output level vs 0 dBFS with attack/release easing, color-coded green/yellow/red, 0 dBFS ceiling notch, -6 dB warning notch, numeric readout.
3. Version counter: `src/version.py` with `__version__ = "1.0.x"`, increment PATCH on every commit. Current: `1.0.38`.
4. Preview screen above scrubbing bar: `PreviewScreen` widget with video title/info.
5. Casting status in details card: Buffer Health and Segments rows.
6. Scrubbing knob moves immediately on seek/jump.
7. UI responsiveness: all blocking I/O in background threads; main thread never blocks.
8. Single-instance GTK/GApplication activation: second launch presents the existing window.
9. Graceful error handling: `main()` wraps `app.run()` in try/except.
10. GUI modernization: refined CSS with better cards, buttons, transport controls, seekbar; larger margins/spacing; larger preview screen; better typography hierarchy; cleaner color scheme; version on front page.
11. A non-blocking background `git pull --ff-only` runs after the first window is visible; a restart applies new Python code.
12. Startup stale-state flush: `_flush_stale_state()` runs in `MainWindow.__init__` after `_build_ui()` to stop any lingering audio analysis, clear session/media/tracker state, and reset all UI widgets to a clean 'nothing playing' state so changes kick in smoothly on restart.
13. Dock: `scripts/install_desktop.py` installs the canonical `local.cast-control.desktop` launcher and matching hicolor icon under `$XDG_DATA_HOME`; absolute `Exec` avoids PATH failures. A hidden `smoothcast.desktop` alias maintains old pins; GNOME favourites referencing the old ID migrate without losing their positions. The installer is idempotent and uses no sudo. Tests: `python3 -m unittest discover -s tests -v`.
14. Server security and reliability: only `movie.m3u8`, `segment-*.ts` and `/_smoothcast/health` are available over HTTP. Port 8767 must pass the SmoothCast-specific health probe before reuse. Stale saved PIDs are checked against Linux `/proc/<pid>/cmdline` before signalling. Failed cast or seek-restart starts clean up spawned subprocesses. Unit tests: `python3 -m unittest discover -s tests -v`.
15. Playback transitions: FFmpeg `-progress` timestamps begin at zero after `-ss` and must be converted to absolute time by `playback_state.absolute_encoded_position`. Queue progression is triggered by a real device PLAYING/PAUSED→IDLE transition, not an encoder/catt exit. Previous-session cleanup must finish before starting Up Next. Pure regression tests live in `tests/test_playback_state.py`.
16. Long-film meter performance: `AudioMonitor._pair` consumes and discards already-converted per-frame FFmpeg metadata dictionaries to keep memory bounded; the compact arrays remain available for seek lookups. `MainWindow._stop_monitor` must retire old FFmpeg analysis off the GTK main thread. Tests: `tests/test_audio_monitor.py`.
17. Chromecast LAN selection: `host_ip(device_host)` picks the outbound interface using a no-packet UDP route to the discovered TV IP, with safe fallbacks. Never advertise loopback, link-local or multicast addresses as HLS URLs. Propagate the selected device IP through normal starts and software-encoder fallback/seek restarts. Regression cases are in `tests/test_streamer_reliability.py`.
18. Startup responsiveness: automatic git updates must run once in a worker **after** GTK window presentation, never before `app.run()`. `--self-test` runs `Gio.ApplicationFlags.NON_UNIQUE` so it cannot activate a live user instance. `app.quit` actions close the window to preserve the normal keep-streaming and configuration lifecycle. Tests: `tests/test_update_control.py`.
19. Encoder fallback: hardware VAAPI is allowed 15s to generate HLS media; software libx264 gets 30s. A stalled but live hardware FFmpeg process must be terminated before one software retry. No infinite fallback loops. `test_stalled_vaapi_encoder_falls_back_even_if_process_is_alive` validates the failure mode.
20. GTK4 action integrity: use `window.fullscreen()/unfullscreen()`, never GTK3-only `set_fullscreen()/set_keep_above()`. Window stacking is compositor-controlled; do not advertise an unsupported always-on-top action. Every `Gio.Menu` entry must correspond to a registered `Gio.SimpleAction`, including `app.clear-recents`.
21. Screenshot capture: `src/screenshot.py` runs FFmpeg only in a background worker with a bounded timeout, no stdin, and a unique non-overwriting output path. Never reintroduce synchronous `subprocess.run` in `MainWindow._screenshot`. Regression tests: `tests/test_screenshot.py`.
22. Real Loop and Sleep timer: `playback_state.next_media` repeats one item before `autonext`; cleanup completes before restarting the same track or auto-shutting down. The sleep timer stores a persisted wall-clock `sleep_timer_deadline` and polls every five seconds, stopping the SmoothCast-owned session. The GTK application must be running for the deadline to fire. Tests: `tests/test_playback_controls.py`.

23. Remote URL casting: `MainWindow._cast_remote_url` validates HTTP(S) addresses with `url_control.validate_media_url`, then calls `catt -d DEVICE cast --no-subs URL` in an `Async.run` worker. Never send network URLs to `streamer.ffprobe(Path(...))`. Tests: `tests/test_url_control.py`.

25. Responsive GTK4 layout: `src/responsive_layout.py` clamps startup size to monitor geometry; `MainWindow._refresh_responsive_layout` checks allocated width/height every 200 ms and reflows cards from a two-column desktop page to a single-column layout below 1180 logical pixels. One outer `Gtk.ScrolledWindow` gives vertical access to every card on short screens. Transport/action controls reattach to compact GTK grids; long metadata wraps and preview text ellipsises. Never restore forced large window minima or GTK3 window-position APIs. See `tests/test_responsive_layout.py` and `tests/test_responsive_wiring.py`.

## Pending work
- Run a real-device smoke test for start, URL cast, seek, loop, stop, auto-shutdown, sleep expiry, VAAPI fallback and keep-streaming (requires a Chromecast on the LAN).

## Completed work
24. Playback speed presets (0.5x–2.0x + custom) now change the actual transcode rate: `setpts=PTS/speed` for video and chained `atempo` for audio are added to the ffmpeg HLS chain; `_set_speed` restarts an active transcode at the current position, and the saved speed is restored across seeks and sessions. Covered by `tests/test_core.py`.

25. Dock artwork: new SmoothCast icon (dark slate squircle, gradient cast glyph with signal arcs, play cutout, glow halo) regenerated offline by `scripts/make_icon.py` and committed at `data/cast-control.png`; `scripts/install_desktop.py --pin` pins SmoothCast to the GNOME dock without reordering existing favorites. Tests: `tests/test_desktop_integration.py`.

26. (none yet — placeholder)
