# SmoothCast

A modern GTK4/libadwaita Chromecast companion with live compressor metering, dialogue auto-fix, and zero flicker.

## Features

- **Live compressor metering** — DJM-style segmented LED meters showing input/output levels and pump/gain reduction in real time, with smooth attack/release ballistics (no flicker); bounded metadata memory for long films and asynchronous FFmpeg shutdown
- **Dialogue auto-fix** — automatic input trim that drives the compressor to always engage, plus acompressor + limiter chain that keeps dialogue audible over action scenes
- **Night mode** — stronger compression for late-night low-volume viewing
- **Live position tracking** — seek bar stays synced with the device in both direct and transcode modes
- **HLS transcoding** — VAAPI H.264 encoding with one bounded software fallback even if the hardware encoder hangs without exiting; picks the LAN source IP routed to the selected Chromecast
- **Direct play** — untouched passthrough for compatible files
- **Subtitle support** — auto-select, burn-in, or disable
- **Queue / Up Next and repeat-one** — advance or loop the current video when the TV reports completion; old stream cleanup finishes before restarting
- **Keyboard shortcuts and capture** — GTK4-compatible fullscreen, working Clear recent files action, and non-blocking, collision-safe FFmpeg screenshots (always-on-top is compositor-controlled)

## Quick start (self-contained)

1. Unzip the release
2. Run:

```sh
./smoothcast
```

That's it. First run creates a `.venv` and installs `catt` automatically. GUI launches also register and repair the dock icon and desktop launcher for your user without sudo.

Optional executable shortcut: `./sc.py` delegates to the same launcher and forwards arguments. If SmoothCast is already running, GTK raises that window; it does not restart an active stream.

## Desktop launcher and dock

SmoothCast registers a desktop entry named `local.cast-control.desktop` to match its GTK application ID and Wayland window identity, with a matching 128×128 icon in the user's XDG hicolor theme directory. The launcher uses the absolute path to this checkout, not an unavailable `smoothcast` executable on `PATH`. A hidden compatibility entry keeps older `smoothcast.desktop` pins launchable; on GNOME, old SmoothCast favourites are migrated to the canonical entry automatically.

To repair or check the launcher explicitly from the checkout:

```sh
python3 scripts/install_desktop.py
python3 scripts/install_desktop.py --check
```

A second launcher click raises the existing window rather than silently exiting. On KDE or other docks, if an old pin remains stale, remove it and pin the new **SmoothCast** entry once. Regression tests: `python3 -m unittest discover -s tests -v`.

## Streaming reliability and local-network safety

The HLS server listens on port 8767 for Chromecast access, but exposes only the generated `movie.m3u8` playlist and `segment-*.ts` media. Internal `session.json`, logs, staged subtitles, and directory listings are inaccessible. SmoothCast checks a dedicated health endpoint before reusing a server; a port conflict produces an actionable error instead of silently streaming from the wrong process. Failed startup or seek-restart attempts clean up child processes, and restored sessions verify Linux PID ownership before terminating saved processes.

Run `python3 -m unittest discover -s tests -v` for the desktop, HTTP server and streamer regression tests.

## Sleep timer

The Sleep timer menu now stops the active SmoothCast session after the selected interval (15–60 minutes). The deadline is saved across application restarts, and can be cancelled with **Off**. The application must remain running for the timer to fire; closing it with Keep streaming enabled does not leave a background scheduler running.

## Automatic updates without blocking startup

Git checkouts perform one background `git pull --ff-only` after the first window appears, not before GTK starts. A successful fast-forward shows a restart notification; code already loaded in the running process is never hot-reloaded. Offline, dirty, or non-git release folders continue to launch normally. `--self-test` uses a separate non-unique application instance so it cannot interfere with a running player.

## Requirements

- **Python 3.10+**
- **GTK4 + libadwaita** (system packages, cannot be pip-installed):
  - Debian/Ubuntu: `sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1`
  - Fedora: `sudo dnf install python3-gobject gtk4 libadwaita`
  - Arch: `sudo pacman -S python-gobject gtk4 libadwaita`
- **ffmpeg** (`sudo apt install ffmpeg` or equivalent)
- **catt** — installed automatically into the bundled venv on first run

## Testing

Pure-logic tests run without GTK or a display:

```sh
python3 -m pytest
```

The GTK UI is verified by the self-test (needs a display, e.g. Xvfb):

```sh
DISPLAY=:99 .venv/bin/python src/cast_control.py --self-test
# prints SELFTEST OK
```

## Architecture

```
smoothcast/
├── smoothcast          # bootstrap launcher (creates venv, installs catt, runs app)
├── requirements.txt    # pip deps (catt)
├── scripts/
│   └── install_desktop.py # user XDG launcher/icon installer
├── src/
│   ├── cast_control.py # main GTK4/Adw app — UI, LevelMeter, MainWindow
│   ├── streamer.py     # HLS transcode, direct play, ffmpeg chains, auto-trim
│   ├── audio_monitor.py# fast precompute + lookup-by-position level analysis
│   ├── castctl.py      # catt CLI wrapper
│   ├── server.py       # HLS static file server
│   ├── error_log.py    # ring-buffer error log (10k lines, gitignored)
│   ├── position_tracker.py — playback position estimation (no GTK dep)
│   └── utils.py        # pure text helpers (pretty_title)
└── data/
    ├── cast-control.png
    └── (desktop entry generated into user XDG applications directory)
```

## How the compressor meter works

The audio monitor runs a fast ffmpeg pass (no `-re`) that splits the audio into two branches:
- **IN** — raw input RMS/peak per channel
- **OUT** — after `volume → acompressor → alimiter` chain

The `LevelSample` carries both, and `gain_db = out_rms - in_rms` shows how much the chain is lifting or pulling. The meter eases displayed values toward each new target with attack (0.55) / release (0.16) ballistics at ~40 fps, so bars glide smoothly without flicker.

## Master meter

A MASTER bouncing-line meter sits below the PUMP strip in the LevelMeter widget. Its height is the post-compressor output level (out_rms), easing with attack/release ballistics so it bounces rather than jumps. It shows at a glance how close the played-back signal is to 0 dBFS: white below -18 dB, yellow -18..-6 dB, red at -6 dB and above, with a tip glow near -3 dB. A faint 0 dBFS ceiling notch marks the top of the scale. The master meter only reflects the transcoded output; direct play passes audio untouched.

## Error log

Uncaught exceptions (main + background threads) and `Async.run` failures are appended to `errors.log`, a ring buffer capped at 10,000 lines (oldest dropped). The file is gitignored and lives at `~/.config/cast-control/errors.log`.

## License

MIT