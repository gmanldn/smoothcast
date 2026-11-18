# SmoothCast

A modern GTK4/libadwaita Chromecast companion with live compressor metering, dialogue auto-fix, and zero flicker.

## Features

- **Live compressor metering** — DJM-style segmented LED meters showing input/output levels and pump/gain reduction in real time, with smooth attack/release ballistics (no flicker)
- **Dialogue auto-fix** — automatic input trim that drives the compressor to always engage, plus acompressor + limiter chain that keeps dialogue audible over action scenes
- **Night mode** — stronger compression for late-night low-volume viewing
- **Live position tracking** — seek bar stays synced with the device in both direct and transcode modes
- **HLS transcoding** — VAAPI hardware-accelerated H.264 encoding with software fallback
- **Direct play** — untouched passthrough for compatible files
- **Subtitle support** — auto-select, burn-in, or disable
- **Queue / Up Next** — auto-play next, drag-reorder
- **Keyboard shortcuts** — space, arrows, etc.

## Quick start (self-contained)

1. Unzip the release
2. Run:

```sh
./smoothcast
```

That's it. First run creates a `.venv` and installs `catt` automatically. Subsequent runs start instantly.

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
    └── smoothcast.desktop
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