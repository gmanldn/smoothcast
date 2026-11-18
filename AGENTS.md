# AGENTS.md — SmoothCast

## Critical rules
- **Commit after every meaningful change.** User loses work if not committed. Run `git add -A && git commit -m "..."` frequently.
- **Commit at least every ~10,000 lines of code or so**, even if the change is small, so work is never lost.
- Never ask the user for confirmation to commit — just do it.
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
- `src/cast_control.py` — main GTK app, LevelMeter widget, MainWindow
- `src/audio_monitor.py` — fast ffmpeg analysis of input/output levels
- `src/streamer.py` — HLS transcode, direct play, ffmpeg chains
- `src/castctl.py` — catt CLI wrapper
- `src/server.py` — HLS static file server
- `src/error_log.py` — ring-buffer error log (errors.log, 10k lines, gitignored)
- `src/position_tracker.py` — playback position estimation (no GTK dep)
- `src/utils.py` — pure text helpers (pretty_title)
- `tests/` — pytest suite (runs without GTK/display)
- `pytest.ini` — pytest config (testpaths, pythonpath=src)

## Testing (portable, GTK-free)
- Run: `python3 -m pytest` (from repo root) — 61 tests, no display needed.
- Logic modules (`position_tracker`, `utils`, `castctl`, `audio_monitor`, `streamer`, `error_log`) import without GTK — safe on CI.
- GTK UI (`cast_control.py`) is covered by the self-test which builds the full window: `DISPLAY=:99 .venv/bin/python src/cast_control.py --self-test`.
- All modules must `compileall` clean; self-test must print `SELFTEST OK`.

## Error log
- Uncaught exceptions (main + background threads) and `Async.run` failures are appended to `errors.log` (ring buffer, max 10,000 lines, gitignored).
- Path: `~/.config/cast-control/errors.log`.

## Versioning
- Tags mark releases, e.g. `v2.0.1`. Bump via `git tag v<major>.<minor>.<patch>` and push tags with `--tags`.

## User's requests (completed)
1. ✅ Compressor only affects playback (transcoded HLS via ffmpeg `-af`), never the host audio stack; direct play untouched; volume/mute via catt to device.
2. ✅ Master bouncing-line meter added to `LevelMeter` (below PUMP strip; attack/release easing; 0/-6 dB notches; red/yellow/white by proximity to 0 dBFS).

## Pending
- None. Working tree clean on `flicker-loganberry`; merge to `main` and tag a release when ready.
