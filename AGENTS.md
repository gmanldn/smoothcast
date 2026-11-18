# AGENTS.md — SmoothCast

## Critical rules (read first)
- **Commit after every meaningful change.** User loses work if not committed. Run `git add -A && git commit -m "..."` frequently.
- **Commit at least every ~10,000 lines of code or so**, even if the change is small, so work is never lost.
- **Never ask the user for confirmation to commit** — just do it.
- **Version counter:** `src/version.py` holds `__version__` = `1.0.x`. Increment the patch number (`x`) on **every single commit**. This makes every build traceable to a specific commit.
- Keep responses short and technical. No preamble, no postamble.

## Project
SmoothCast is a GTK4/libadwaita Chromecast companion app.
- Launcher: `./smoothcast` (creates `.venv`, installs catt, runs `src/cast_control.py`)
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
- `src/server.py` — HLS static file server
- `src/version.py` — version counter (MAJOR.MINOR.PATCH, bump patch on every commit)

## Architecture
- GTK4 + libadwaita UI runs on the main thread via `Adw.Application`.
- All blocking I/O (castctl, ffmpeg, network) runs in background threads via `Async.run()` and is marshalled back to the main thread with `GLib.idle_add()`.
- The compressor (`acompressor` + `alimiter`) lives in `streamer.py:AUDIO_FILTERS` and is applied **only** in the ffmpeg transcode chain that produces the HLS stream sent to the Chromecast. It does **not** affect local machine audio, the original file, or any other application.
- The audio monitor (`audio_monitor.py`) runs a separate read-only ffmpeg pass for metering; it never touches playback.

## Version
- `src/version.py`: `__version__ = "1.0.x"` — increment `PATCH` on every commit.
- Current: `1.0.1`

## Completed work
1. Compressor only affects playback (verified by code inspection).
2. Bouncing master line meter added to `LevelMeter` — shows post-compressor output level vs 0 dBFS with attack/release easing, color-coded green/yellow/red, 0 dBFS ceiling notch, -6 dB warning notch, numeric readout.

## Pending work
1. Add casting status detail to main window (state, mode, buffer health).
2. Add preview screen above scrubbing bar.
3. Make scrubbing knob move immediately on seek/jump (UI shows target instantly while cast catches up).
4. Keep UI responsive — offload all blocking work to background threads.
