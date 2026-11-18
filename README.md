# SmoothCast

A modern GTK4/libadwaita Chromecast companion with live compressor metering, dialogue auto-fix, and zero flicker.

## Features

- **Live compressor metering** — DJM-style segmented LED meters showing input/output levels and pump/gain reduction in real time, with smooth attack/release ballistics (no flicker); bounded metadata memory for long films and asynchronous FFmpeg shutdown
- **Dialogue auto-fix** — automatic input trim that drives the compressor to always engage, plus acompressor + limiter chain that keeps dialogue audible over action scenes
- **Night mode** — stronger compression for late-night low-volume viewing
- **Live position tracking** — seek bar stays on the original film timeline through pause/resume, seeks and 0.5×–2× playback; HLS time is converted to source time
- **Responsive window** — sizes itself to the monitor, stacks cards as the window narrows, wraps playback buttons, and scrolls the full page vertically rather than clipping
- **Refined media-console interface** — purpose-built Now Playing slate, primary Open video action, readable transport controls, compact queue and activity empty states, live device badges, grouped sound/video/subtitles settings and structured technical diagnostics
- **HLS transcoding** — VAAPI H.264 encoding with one bounded software fallback even if the hardware encoder hangs without exiting; picks the LAN source IP routed to the selected Chromecast
- **Direct play** — untouched passthrough for compatible files; playback speed/rotation automatically switch to the transcode path
- **Remote URL casting** — Open URL validates HTTP(S) addresses and calls catt asynchronously; invalid URLs and device errors are reported instead of treating the URL as a local file
- **Subtitle support** — auto-select, burn-in, or disable
- **Queue / Up Next and repeat-one** — advance or loop when the TV reports completion; old stream cleanup finishes before restarting
- **Reliable M3U playlists and resume** — atomic save/load, deduplication and missing-file handling; remembered positions never override an explicit rewind
- **Keyboard shortcuts and capture** — GTK4-compatible fullscreen, working Clear recent files action, and non-blocking, collision-safe FFmpeg screenshots (always-on-top is compositor-controlled)

## Quick start (self-contained)

1. Unzip the release
2. Run:

```sh
./smoothcast
```

That's it. First run creates a `.venv` and installs `catt` automatically. GUI launches also register and repair the dock icon and desktop launcher for your user without sudo.

Optional executable shortcut: `./sc.py` delegates to the same launcher and forwards arguments. If SmoothCast is already running, GTK raises that window; it does not restart an active stream.

## Install via pip (recommended for Python workflows)

```sh
pip install -e .
# or from a release tarball
pip install smoothcast
```

Then run `smoothcast` or `sc` directly. The pip entry point is the canonical way forward; the `./smoothcast` bash launcher is a convenience for non-Python workflows and will delegate to the installed entry point in a future version.

## Interface and visual design

SmoothCast uses a consistent midnight-blue GTK4 palette, 14px base text, higher-contrast secondary labels, a contextual primary action (Open before selection, Cast afterward) and compact technical panels. The film preview is deliberately an illustrated metadata slate rather than a fake video screenshot. The queue and event console occupy minimal space when empty and become scrollable only when there is content. The device card distinguishes a Chromecast found on the network from one confirmed reachable by a status query. Playback settings are grouped by function; diagnostics show separate playback/encoder and media/output sections.

The design follows GNOME's [Human Interface Guidelines on adaptive layout](https://developer.gnome.org/hig/guidelines/adaptive.html) and [typography](https://developer.gnome.org/hig/guidelines/typography.html). Media-player hierarchy draws on familiar patterns from IINA and Plexamp, while keeping functional GTK4/libadwaita controls. Colours and selectors are maintained centrally in `src/ui_theme.py`; `tests/test_visual_design.py` checks contrast and core UI wiring.

## Playback reliability

Speed and rotation selections are preserved if the VAAPI encoder stalls and restarts with the software encoder. For faster/slower playback, FFmpeg reads input at the selected speed (`-readrate`) while rescaling video and audio presentation timestamps. The seekbar, saved position and live device/encoder feedback remain in source-video seconds. Changing speed during direct play transparently starts a transcode of the selected video.

Stop and Pause remain available while the TV consumes a completed HLS buffer. SmoothCast also rejects outdated device replies and avoids switching TV targets mid-cast. A saved direct cast is only reattached when the Chromecast still reports compatible playback.

The portable unit tests and syntax checks now run on pushes and pull requests via [Verify SmoothCast](https://github.com/gmanldn/smoothcast/actions/workflows/verify.yml). Actual GTK rendering and real Chromecast playback still require a local smoke test.

## Playlists, resume and safe playback transitions

**Save playlist** writes an atomic local `smoothcast_playlist.m3u` under your home directory. **Load playlist** accepts M3U comments and relative paths, skips missing/unavailable entries and removes duplicates without changing the Loop setting. The Loop menu action independently toggles repeat-one.

Opening a previously watched video can resume from its saved position. An intentional jump to **00:00** always goes to the start; automatic Up Next also starts the next film at zero. Direct Chromecast playback seeks to the remembered position, falling back to the transcoder if the receiver cannot seek.

When one film finishes, the UI holds incoming cast commands until the old server and HLS files have been cleaned up, avoiding overlap between sessions. Once the TV reports that a movie ended, cleanup does not send an unnecessary second Stop command that might interrupt other playback.

## Responsive sizing

The application no longer requires fullscreen or a 1400-pixel-wide minimum window. Saved startup dimensions are bounded by the detected monitor's logical geometry, leaving space for decorations. Layout automatically reflows on resize: **1180+ logical px** shows two columns; narrower widths stack cards. Transport controls and action buttons wrap as needed, preview height and card padding become more compact, and one outer vertical scroller keeps every card accessible even when the window is shorter than the full interface. Resizing wider restores the two-column layout. The app avoids shrinking controls to unreadable sizes.

The geometry and breakpoint decisions are independently testable in `src/responsive_layout.py`. Run `python3 -m unittest discover -s tests -v` for breakpoint and GTK structure regression checks.

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

## Clean startup and orphan recovery

When a **new primary SmoothCast process** launches, it recovers from any old crashed session *before constructing the GTK window*. Linux process checks identify only this user's SmoothCast-owned HLS server, FFmpeg encoder, FFmpeg audio-monitor and ffplay preview helpers. The check verifies command-line signatures and process start times before sending SIGTERM, escalating only stubborn verified leftovers. This is not a blanket kill of other FFmpeg, Python or catt jobs.

The recovery clears stale HLS playlist/segments, progress metadata and orphaned audio-meter scratch directories. Configuration, diagnostic logs and video files are retained. An existing cast deliberately left playing through **Keep streaming after closing** is preserved and reattached normally; a direct cast keeps its session record but drops unused HLS output. A second click on the dock simply raises the existing application and never repeats cleanup. `--self-test` also skips recovery to avoid disturbing your running session.

Startup recovery reports its actions in the terminal and the application's activity console. Pure-Python regression checks: `python3 -m unittest tests.test_startup_cleanup -v` (or the complete suite with `python3 -m unittest discover -s tests -v`).

## Canonical version and build identity

`src/version.py` is the **single authority** for the SmoothCast release:
`MAJOR.MINOR.PATCH` is constructed once and imported throughout the running
application. The exact Git commit SHA identifies individual development changes;
do not treat each small commit as a separate release.

To inspect the installed version **without launching GTK, repairing the dock or
starting the virtual environment**, run:

```sh
./smoothcast --version
# or ./sc.py --version
# or python3 src/version.py
```

The **window title** always shows the version of the **running** SmoothCast
process; **About** uses exactly the same value. When an asynchronous git pull
downloads a new release, the notice explicitly distinguishes the downloaded
version from the still-running version, and the header displays a restart
reminder. The new version takes effect only after closing and relaunching.

CI includes `tests/test_version_integrity.py` to check the canonical source,
CLI output, UI wiring and documentation; do not maintain a second
hardcoded "Current: X.Y.Z" version elsewhere.

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

## Troubleshooting tests and GTK sizing

Use `python3 -m unittest discover -s tests -v` to run all GTK-independent regression tests. A previously observed set of local-playback test errors was caused by using the `mock.patch` context manager object instead of the object returned by `patcher.start()`; make sure the current `tests/test_local_playback.py` is committed and all patches are stopped in teardown. Screenshot capture now verifies input and output using filesystem metadata, including that FFmpeg actually produced a non-empty file.

For the main window, the queue and activity list scrollers have fixed height bounds and no longer propagate unstable child natural heights into the parent box. The **outer** page scroller still makes all controls available on smaller displays. This addresses a potential cause of GTK measure warnings; actual on-screen validation is still required.

## Error log

Uncaught exceptions (main + background threads) and `Async.run` failures are appended to `errors.log`, a ring buffer capped at 10,000 lines (oldest dropped). The file is gitignored and lives at `~/.config/cast-control/errors.log`.

## License

MIT