# SmoothCast

A modern GTK4/libadwaita Chromecast companion with live compressor metering, dialogue auto-fix, and zero flicker.

## Features

- **Live compressor metering** — DJM-style segmented LED meters showing input/output levels and pump/gain reduction in real time, with smooth attack/release ballistics (no flicker); bounded metadata memory for long films and asynchronous FFmpeg shutdown
- **Dialogue auto-fix** — automatic input trim that drives the compressor to always engage, plus acompressor + limiter chain that keeps dialogue audible over action scenes
- **Night mode** — stronger compression for late-night low-volume viewing
- **Live position tracking** — seek bar stays on the original film timeline through pause/resume, seeks and 0.5×–2× playback; HLS time is converted to source time
- **Responsive window** — sizes itself to the monitor, stacks cards as the window narrows, wraps playback buttons, and scrolls the full page vertically rather than clipping
- **Refined media-console interface** — purpose-built Now Playing slate, primary Open video action, readable transport controls, compact queue and activity empty states, live device badges, grouped sound/video/subtitles settings and structured technical diagnostics
- **HLS transcoding** — Linux VAAPI H.264 encoding with a bounded software fallback; macOS/Windows start with software libx264; selects the LAN source IP routed to the Chromecast
- **Direct play** — untouched passthrough for compatible files; playback speed/rotation automatically switch to the transcode path
- **Remote URL casting** — Open URL validates HTTP(S) addresses and calls catt asynchronously; invalid URLs and device errors are reported instead of treating the URL as a local file
- **Subtitle support** — load an explicit .srt/.vtt/.ttml file, auto-match sidecars, choose an embedded MKV text track, or burn captions into H.264 video
- **Searchable queue** — Ctrl+F filters filenames and folder paths; selecting or activating a filtered row uses the correct file identity, and reordering/removal preserves selection where possible
- **Queue / Up Next and repeat-one** — advance or loop when the TV reports completion; old stream cleanup finishes before restarting
- **Reliable M3U playlists and resume** — atomic save/load, deduplication and missing-file handling; remembered positions never override an explicit rewind
- **Keyboard shortcuts and capture** — GTK4-compatible fullscreen, working Clear recent files action, and non-blocking, collision-safe FFmpeg screenshots (always-on-top is compositor-controlled)

## Install — Python-first, all three desktops

**The only manual prerequisite is Python 3.10+**. Setup will check and, where necessary, install GTK4, libadwaita, PyGObject, FFmpeg/ffplay/ffprobe and `catt`. The installer uses the host package manager and may request administrator permission. Internet access is required for missing packages.

| OS | Setup command | Application shortcut |
|---|---|---|
| Debian/Ubuntu, Fedora, Arch | `bash setup/linuxsetup.sh` | Linux application menu / GNOME dock |
| macOS | `bash setup/macsetup.sh` | `~/Applications/SmoothCast.app` |
| Windows 10/11 x64 | Double-click `setup/winsetup.bat` | Windows Start Menu |

The three scripts delegate to the same stdlib-only `setup/bootstrap.py`, which verifies an isolated `.venv` before registering the desktop shortcut. Rerunning setup checks for missing dependencies; `--check` performs read-only health checks. `--no-shortcuts` skips desktop integration. See [setup/README.md](setup/README.md) for platform-specific details and limitations.

On Linux/macOS, `python3 sc.py` launches the configured runtime across platforms. Version lookup remains side-effect free: `smoothcast --version` (Unix) or `python src/version.py` (any OS).

**Cross-platform status:** Linux is the existing working implementation. The Windows and macOS native setup/bootstrap paths are now implemented and covered by portable tests, but have **not** yet passed end-to-end GUI and Chromecast tests on those machines. Windows uses MSYS2 UCRT64, whose Python extension packaging differs from official CPython; the `catt` installation may require follow-up dependency work. Both systems initially use software libx264 rather than Linux VAAPI.

### Development installs with pip

For an environment where GTK4/libadwaita and FFmpeg are already available, the Python package can be installed with `python -m pip install -e .`. Plain `pip install` cannot provide the required native GTK stack; the platform setup scripts are the recommended first-install path.

## Cast targets, MKV codecs and subtitle files

**Google Cast-compatible receivers:** SmoothCast discovers Chromecast,
Google TV Streamer, Google TV / Android TV Cast receivers, smart TVs with
Google Cast built in, and compatible Google Nest displays through the catt
Google Cast backend. The receiver must actually expose Google Cast; a
generic Wi-Fi TV is not sufficient. If mDNS discovery fails, use **Output
device → Add IP** with the receiver's private-LAN IPv4 address, then select
it in the output dropdown. A manual IP only targets Google Cast receivers,
not DLNA, AirPlay or Miracast. **AirPlay and Miracast remain unimplemented.**

**DLNA / UPnP MediaRenderer (beta):** SmoothCast also scans for
AVTransport-compatible DLNA renderers on the private LAN using SSDP. Choose an
entry labelled **DLNA · TV name · IP** in **Output device**, then press **Cast**.
The application supplies a temporary HTTP URL with an unguessable token and
byte-range requests; the TV fetches a progressive MP4 from your machine.
Playback, pause, stop, seek and optional volume controls use UPnP SOAP, **not**
the Google Cast backend. A receiver must advertise a compatible DLNA
AVTransport service; some TVs with only UPnP *media browsing* are not
MediaRenderers and will not be listed.

For compatible H.264/AAC MP4 files, DLNA playback starts directly. An MKV
with compatible tracks is remuxed to a temporary MP4; incompatible codecs,
non-default audio tracks or selected subtitles require full FFmpeg
transcoding and burn-in **before playback starts**. For long films this can
take significant time and disk space (roughly twice the source-file size must
be available). The application checks local free space, refuses a conversion
larger than the scratch cap (`cache_cap_mb` in `~/.config/cast-control/config.json`,
default 8192 MB, `0` = unlimited) before FFmpeg starts, sweeps scratch left by a
crash (`smoothcast-dlna-*` in the system temp directory, once older than 10
minutes) at the next startup, and reports conversion errors. FFmpeg runs at below-normal priority (nice 10 on Linux/macOS, `BELOW_NORMAL_PRIORITY_CLASS` on Windows) so the desktop stays responsive during software encodes; set `"lower_ffmpeg_priority": false` in the same config file to opt out. The DLNA target path currently uses normal playback speed, no video
rotation and the original sound profile; Chromecast still supports its own
transcode and audio processing. SRT/ASS burn-in on DLNA depends on libass
support in your FFmpeg build.

DLNA discovery currently requires private IPv4 SSDP responses with a matching
HTTP device-description host. VPNs, Wi-Fi isolation and firewall rules may
prevent discovery or TV-to-computer HTTP connections. Stopping SmoothCast
also stops its private DLNA HTTP server, even if **Keep streaming** is enabled.
DLNA has automated protocol tests but **has not yet been verified on a real
television**; device-specific MIME/codec negotiation is a follow-up in
[GitHub issue #8 (SC-001)](https://github.com/gmanldn/smoothcast/issues/8).

**MKV/Matroska:** FFprobe detects embedded video/audio/subtitle streams.
Common video codecs H.264, HEVC/H.265, VP9 and AV1 and audio codecs AAC,
AC-3/E-AC-3, DTS, Opus and FLAC can be decoded and *transcoded* by a suitably
built FFmpeg into H.264 8-bit 4:2:0/AAC HLS for Cast. In software mode the
output is bounded to 1080p and high-frame-rate sources to 30 fps for older
receiver compatibility. **Playback settings → Film audio track** lists
FFprobe-detected audio languages, titles, codecs and channel layouts.
Choose Auto or a specific track before casting. Explicit selection disables
direct passthrough and uses transcoded HLS; changing the track while casting
restarts the stream at the current source-film position. Per-film choices
persist through seeks and codec fallback. Actual playback
depends on the installed FFmpeg build and receiver; DRM-protected files
and some unusual encodings are not guaranteed.

**Subtitles:** In **Playback settings → Subtitles**, use **Pick .srt /
subtitles…** and choose an existing .srt, .vtt, .ttml, .ass or .ssa file.
For external SRT files, SmoothCast recognises UTF-8 (with or without BOM),
UTF-16 little/big-endian (with or without BOM when identifiable), and legacy
Windows-1252. It verifies the captions and stages a private UTF-8 copy
(mode 0600 on POSIX) for both Cast receiver subtitles and FFmpeg burn-in.
The original subtitle file is never rewritten. Invalid or oversized (over
16 MiB) captions produce a visible error before starting playback.
For SRT/VTT/TTML, SmoothCast can send a separate caption track to the Cast
receiver; enable **Burn subtitles into video** when your TV does not display
it reliably. ASS/SSA always use burn-in, because catt does not accept them
as external receiver tracks. **Auto** chooses a same-name sidecar
(`Film.srt` or `Film.en.srt`) first; otherwise it uses a compatible
embedded MKV text track. **Embedded (MKV track)** lets you choose a
particular track and language; an embedded track is burned into the
transcoded picture. PGS/VobSub/DVB bitmap subtitles are detected but
**not yet rendered**. Missing or incompatible subtitle files return a
visible error instead of silently proceeding with another track.

## Interface and visual design

**Preferences:** choose **Preferences…** from the main menu, use **Ctrl+,**,
or select **Open Preferences…** in the Playback settings card. A searchable,
native libadwaita window groups Picture and delivery, Queue behaviour, Audio,
Captions and Appearance with per-setting explanations and explicit notes about
when a new cast or encoder restart is required. The main playback card starts
compact; expand **Show inline playback controls** to use the familiar controls.
Both views edit the same saved preferences through the existing callbacks.
Film-specific audio/embedded caption tracks are only enabled when available.
No settings operation contacts a TV merely by opening the window.

This follows GNOME's guidance on [adaptive layouts](https://developer.gnome.org/hig/guidelines/adaptive.html),
[application preferences](https://developer.gnome.org/hig/patterns/controls/menus.html)
and [GTK main-thread ownership](https://docs.gtk.org/gtk4/section-threading.html).

SmoothCast uses a consistent midnight-blue GTK4 palette, 14px base text, higher-contrast secondary labels, a contextual primary action (Open before selection, Cast afterward) and compact technical panels. The local preview shows real decoded frames while scrubbing and an embedded video player on Play; a metadata slate is retained as the empty or decode-error fallback. The queue and event console occupy minimal space when empty and become scrollable only when there is content. The device card distinguishes a Chromecast found on the network from one confirmed reachable by a status query. Playback settings are grouped by function; diagnostics show separate playback/encoder and media/output sections.

The design follows GNOME's [Human Interface Guidelines on adaptive layout](https://developer.gnome.org/hig/guidelines/adaptive.html) and [typography](https://developer.gnome.org/hig/guidelines/typography.html). Media-player hierarchy draws on familiar patterns from IINA and Plexamp, while keeping functional GTK4/libadwaita controls. Colours and selectors are maintained centrally in `src/ui_theme.py`; `tests/test_visual_design.py` checks contrast and core UI wiring.

## Inspect and scrub a film before casting

Choose **Open** and select a local film. FFprobe enumerates its full duration and codec details once; its metadata stays cached while the file size and modification timestamp match. You can drag the timeline to a particular scene without casting. The still-image scrubber extracts bounded frames with FFmpeg, off the GTK event loop.

**Play** (or Space) now starts the movie **inside the preview panel**, with local audio. Play again to pause. The seek bar, jump buttons and number-key shortcuts change the local movie position; the playhead advances in real time without ever rerunning FFprobe on each scrub or tick. This preview works even when no Chromecast is connected. **Stop** resets only the local preview.

Choose a Google Cast or DLNA renderer in the device selector, then press **Cast**. SmoothCast stops the local decoder, captures its most recent playback timestamp and starts casting at that position. After transfer, Play/Pause and seeking control the TV as before. The **Play preview** button does the same as the main Play control while no TV cast is active. Queue double-click remains an explicit immediate cast action.

Embedded playback uses GTK4's native GStreamer media backend; still-frame scrubbing continues to use FFmpeg. On Debian/Ubuntu, install the media backend and codecs with `bash setup/linuxsetup.sh` (including `libgtk-4-media-gstreamer`, `gstreamer1.0-plugins-good` and `gstreamer1.0-libav`). If a codec is unsupported, a decoder error is reported and the still-frame preview remains available. Windows/macOS GTK media backend and real-device casting still require native smoke testing.

## MKV decoder preflight

On the first cast of an MKV, SmoothCast checks the film **before stopping the
currently playing TV**. FFmpeg decodes a short (0.8-second) sample using the
selected audio stream and any required text subtitle filter, encodes it
privately to H.264/AAC, then FFprobe verifies that real video frames were
produced. Temporary media/captions are deleted after the check. A clear
local error is shown if a decoder, audio track, subtitle filter or encoder
is missing; no cast command is sent for a failed preflight.

Successful checks are cached for the running app by media size/mtime, subtitle
size/mtime, audio choice and burn/embedded subtitle selection. Changing the
file or track triggers a new check. This can add up to 20 seconds on a first
cast, but repeated unmodified films skip the dry run. **A passed local
preflight is not a guarantee that a particular TV, GPU or network can cast**
the stream; it validates the software decoding and selected subtitle path.

## Playback reliability

Speed and rotation selections are preserved if the VAAPI encoder stalls and restarts with the software encoder. For faster/slower playback, FFmpeg reads input at the selected speed (`-readrate`) while rescaling video and audio presentation timestamps. The seekbar, saved position and live device/encoder feedback remain in source-video seconds. Changing speed during direct play transparently starts a transcode of the selected video.

Stop and Pause remain available while the TV consumes a completed HLS buffer. SmoothCast also rejects outdated device replies and avoids switching TV targets mid-cast. A saved direct cast is only reattached when the Chromecast still reports compatible playback.

The portable unit tests and syntax checks now run on pushes and pull requests via [Verify SmoothCast](https://github.com/gmanldn/smoothcast/actions/workflows/verify.yml). Actual GTK rendering and real Chromecast playback still require a local smoke test.

## Opening media from another directory

Running `./smoothcast relative-film.mkv` from a media directory resolves
the filename against that directory **before** the launcher changes into the
checkout for dependency loading. When a second command reaches an already
running instance, `GApplicationCommandLine.get_cwd()` supplies the original
caller's directory. This also prevents a same-named file in the checkout from
silently replacing a missing caller file. Absolute paths and `file://` media
URIs keep their original meaning.

## Playlists, resume and safe playback transitions

**Save playlist** writes an atomic local `smoothcast_playlist.m3u` under your home directory. **Load playlist** accepts M3U comments and relative paths, skips missing/unavailable entries and removes duplicates without changing the Loop setting. The Loop menu action independently toggles repeat-one.

Opening a previously watched video can resume from its saved position. An intentional jump to **00:00** always goes to the start; automatic Up Next also starts the next film at zero. Direct Chromecast playback seeks to the remembered position, falling back to the transcoder if the receiver cannot seek.

When one film finishes, the UI holds incoming cast commands until the old server and HLS files have been cleaned up, avoiding overlap between sessions. Once the TV reports that a movie ended, cleanup does not send an unnecessary second Stop command that might interrupt other playback.

## Responsive sizing

The application no longer requires fullscreen or a 1400-pixel-wide minimum window. Saved startup dimensions are bounded by the detected monitor's logical geometry, leaving space for decorations. Layout automatically reflows on resize: **1180+ logical px** shows two columns; narrower widths stack cards. Transport controls and action buttons wrap as needed, preview height and card padding become more compact, and one outer vertical scroller keeps every card accessible even when the window is shorter than the full interface. Resizing wider restores the two-column layout. The app avoids shrinking controls to unreadable sizes.

The geometry and breakpoint decisions are independently testable in `src/responsive_layout.py`. Run `python3 -m unittest discover -s tests -v` for breakpoint and GTK structure regression checks.

## Desktop launcher and dock

SmoothCast registers a desktop entry named `local.cast-control.desktop` to match its GTK application ID and Wayland window identity, with a matching 128×128 icon in the user's XDG hicolor theme directory. The desktop entry's `Exec` is the **absolute path to this checkout's `./smoothcast` launcher**, not a potentially older `smoothcast` found on `PATH`. A hidden compatibility entry keeps older `smoothcast.desktop` pins launchable; on GNOME, old SmoothCast favourites are migrated to the canonical entry automatically.

To repair the existing Linux dock icon after pulling a new version (run from your SmoothCast checkout, without `sudo`):

```sh
git pull --ff-only
bash setup/linuxsetup.sh
python3 scripts/install_desktop.py --pin
python3 scripts/install_desktop.py --check
grep '^Exec=' ~/.local/share/applications/local.cast-control.desktop
```

The installer refreshes `~/.local/share/applications/local.cast-control.desktop` and `~/.local/share/icons/hicolor/128x128/apps/local.cast-control.png`. The desktop entry launches this checkout's `smoothcast` script with a fixed working directory; a missing or incomplete project virtualenv is repaired on launch. `--pin` adds the canonical entry to GNOME favourites without duplicating or rearranging other favourites. The read-only `--check` and `grep` commands validate the desktop entry **without launching a window or stealing focus**.

To diagnose an old version or repeated launch, compare the checkout version with the dock's actual executable:

```sh
cd /path/to/smoothcast
git pull --ff-only
python3 src/version.py
python3 scripts/install_desktop.py --pin
python3 scripts/install_desktop.py --check
grep '^Exec=' ~/.local/share/applications/local.cast-control.desktop
```

The dock must point to the **absolute path to the launcher in this checkout**.
Running `python3 sc.py` from this directory bypasses any old dock entry.
A dependency repair now installs from `pyproject.toml`, not a missing
`requirements.txt`; repair failures print the actual error rather than
pretending that the same release installed again.

If the menu entry is missing despite a successful read-only check, log out and back in to refresh GNOME's application cache. To diagnose a user-initiated launch failure (not an automated test), run `python3 sc.py` from the same checkout in a terminal; on GNOME, inspect `journalctl --user -b`. Do not use `sudo` for desktop integration because it would install the icon under root's account.

A second launcher click raises the existing window rather than silently exiting. On KDE or other docks, if an old pin remains stale, remove it and pin the new **SmoothCast** entry once. Regression tests: `python3 -m unittest discover -s tests -v`.

## Streaming reliability and local-network safety

The HLS server listens on port 8767 for Chromecast access, but **only on loopback plus the single LAN interface chosen for the receiver's route — never `0.0.0.0`** — and answers `403 Forbidden` to every client except the receiver and loopback (loopback keeps `/_smoothcast/health` working). The allowed receiver is published in `~/.cache/cast-control/server_access.json` before each cast and re-read per request, so a server kept alive by *Keep streaming* follows the new receiver; a kept server bound to a different interface is replaced only after its PID is verified as SmoothCast's own, otherwise the cast is refused with an actionable error. IPv4-mapped IPv6 clients are judged by their IPv4 address, public addresses are never allowed, and when the receiver's address is unknown (a cast selected by name) only private-LAN clients (RFC 1918 / link-local) are accepted. A real Chromecast must still be confirmed to play the stream (device-pending). It exposes only the generated `movie.m3u8` playlist and `segment-*.ts` media. Internal `session.json`, logs, staged subtitles, and directory listings are inaccessible. HLS responses omit cross-origin wildcard headers; native receiver playback must be qualified on hardware. SmoothCast checks a dedicated health endpoint before reusing a server; a port conflict produces an actionable error instead of silently streaming from the wrong process. Failed startup or seek-restart attempts clean up child processes, and restored sessions verify Linux PID ownership before terminating saved processes.

Run `python3 -m unittest discover -s tests -v` for the desktop, HTTP server and streamer regression tests.

## Sleep timer

The Sleep timer menu now stops the active SmoothCast session after the selected interval (15–60 minutes). The deadline is saved across application restarts, and can be cancelled with **Off**. The application must remain running for the timer to fire; closing it with Keep streaming enabled does not leave a background scheduler running.

## Clean startup and orphan recovery

When a **new primary SmoothCast process** launches, it recovers from any old crashed session *before constructing the GTK window*. Linux process checks identify only this user's SmoothCast-owned HLS server, FFmpeg encoder, FFmpeg audio-monitor and ffplay preview helpers. The check verifies command-line signatures and process start times before sending SIGTERM, escalating only stubborn verified leftovers. This is not a blanket kill of other FFmpeg, Python or catt jobs.

The recovery clears stale HLS playlist/segments, progress metadata and orphaned audio-meter scratch directories. Configuration, diagnostic logs and video files are retained. An existing cast deliberately left playing through **Keep streaming after closing** is preserved and reattached normally; a direct cast keeps its session record but drops unused HLS output. A second click on the dock simply raises the existing application and never repeats cleanup. `--self-test` also skips recovery to avoid disturbing your running session.

Startup recovery reports its actions in the terminal and the application's activity console. Pure-Python regression checks: `python3 -m unittest tests.test_startup_cleanup -v` (or the complete suite with `python3 -m unittest discover -s tests -v`).

## Canonical version and build identity

`src/version.py` is the **single authority** for the SmoothCast release: `MAJOR.MINOR.PATCH` is constructed once and imported throughout the running application. The exact Git commit SHA identifies individual development changes; do not treat each small commit as a separate release.

To inspect the installed version **without launching GTK, repairing the dock or starting the virtual environment**, run:

```sh
smoothcast --version
# or sc --version
# or python3 src/version.py
```

The **window title** always shows the version of the **running** SmoothCast process; **About** uses exactly the same value. When an asynchronous git pull downloads a new release, the notice explicitly distinguishes the downloaded version from the still-running version, and the header displays a restart reminder. The new version takes effect only after closing and relaunching.

CI includes `tests/test_version_integrity.py` to check the canonical source, CLI output, UI wiring and documentation; do not maintain a second hardcoded "Current: X.Y.Z" version elsewhere.

## Automatic updates without blocking startup

Git checkouts perform one background `git pull --ff-only` after the first window appears, not before GTK starts. Only a **new semantic version** generates a restart notification: ordinary commits to the same version never ask you to restart again. Code already loaded in the running process is never hot-reloaded. Offline, dirty, or non-git release folders continue to launch normally. `--self-test` uses a separate non-unique application instance so it cannot interfere with a running player.

## Runtime dependencies

Python 3.10+ is the only dependency users must install themselves. The platform setup scripts automatically detect or provision native GTK4, libadwaita, PyGObject, FFmpeg/ffprobe/ffplay, and `catt` inside the project virtual environment. This still requires network access, a supported system package manager and permission to install system packages. Verify without modifying anything using `--check`.

## Token-efficient coding agents

SmoothCast includes project-scoped [Caveman](.kilo/skills/caveman/SKILL.md)
(concise technical responses) and
[Ponytail](.kilo/skills/ponytail/SKILL.md)
(minimal complete diffs) instruction skills. The root
[AGENTS.md](AGENTS.md) has been reduced by **88% in characters**;
the original instructions remain intact in
[docs/AGENT_REFERENCE.md](docs/AGENT_REFERENCE.md).
See [agent token efficiency](docs/AGENT_TOKEN_EFFICIENCY.md) for
measurement limitations and optional official upstream plugins. These
repo-local instructions do **not** install a proxy, change user
credentials or add SmoothCast runtime dependencies.

## Testing — never steal desktop focus

Normal regression testing is intentionally **headless**, even if a developer
has an active Wayland or X11 session:

```sh
python3 -m pytest -q tests
python3 -m compileall -q src scripts setup tests
```

These commands do not launch SmoothCast or bring an existing window to the
foreground. Pytest marks its subprocesses with a GUI refusal flag, and direct
`--self-test` on the normal launcher is refused before bootstrap.

**Version coverage:** GitHub Actions runs the **entire** portable pytest suite
and Python syntax check using both Python **3.10** (the published minimum)
and Python **3.13** (the primary development interpreter). Unlike bare
`unittest discover`, pytest collects both `unittest.TestCase` methods
and standalone `test_*` functions. The separate cross-platform setup
matrix intentionally uses
`python3 -m unittest discover -s tests -p "test_setup_bootstrap.py" -v`
for installer-only contracts; it does **not** replace the full portable suite.

A real GTK widget-construction smoke test is **optional**, run only when
explicitly needed, through a disposable virtual display:

```sh
# Debian/Ubuntu, if not installed: sudo apt-get install xvfb xauth
python3 scripts/test_gui_isolated.py
# Builds GTK under a private Xvfb display and exits with SELFTEST OK.
```

The runner has a strict timeout and kills the complete Xvfb/UI process group
if it hangs. It isolates `HOME`, XDG config/data/cache, Xauthority and
session DBus; it never uses the desktop's `DISPLAY` or `WAYLAND_DISPLAY`,
never discovers TV devices and does not change dock integration. It refuses
to run when Xvfb is unavailable instead of opening a real window.
**Do not use `DISPLAY=:0 smoothcast --self-test` or manually launch the
GUI repeatedly during automated testing.** Source-level UI wiring and
responsive layout tests are included in normal pytest.

## Architecture

```
smoothcast/
├── pyproject.toml    # canonical packaging metadata + console-script entry points
├── setup.py          # shim delegating to pyproject.toml
├── setup/              # Python-only bootstrap, native OS installers and launchers
│   ├── winsetup.bat    # Windows/MSYS2 UCRT64 bootstrap
│   ├── macsetup.sh     # macOS/Homebrew bootstrap
│   ├── linuxsetup.sh   # apt/dnf/pacman bootstrap
│   ├── bootstrap.py    # dependency installation and validation
│   ├── launch.py       # portable non-mutating runtime launcher
│   └── shortcuts.py    # native desktop integration
├── scripts/
│   └── install_desktop.py # user XDG launcher/icon installer
├── src/
│   ├── cast_control.py # main GTK4/Adw app — UI, LevelMeter, MainWindow
│   ├── streamer.py     # HLS transcode, direct play, ffmpeg chains, auto-trim
│   ├── audio_monitor.py# fast precompute + lookup-by-position level analysis
│   ├── castctl.py      # catt CLI wrapper
│   ├── server.py       # HLS static file server
│   ├── playlist_control.py # portable M3U playlist I/O
│   ├── error_log.py    # ring-buffer error log (10k lines, gitignored)
│   ├── position_tracker.py — playback position estimation (no GTK dep)
│   └── utils.py        # pure text helpers (pretty_title)
└── data/
    └── cast-control.png
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

Uncaught exceptions (main + background threads) and `Async.run` failures are appended to `errors.log` without rewriting the entire history per entry. The log keeps at most 10,000 recent lines/entries and 2 MiB of retained data, compacting atomically when it exceeds 4 MiB. Old oversized logs are read from a bounded tail only, and a single enormous error is truncated while retaining its beginning and final cause. It is gitignored at `~/.config/cast-control/errors.log`.

## Support diagnostics

SmoothCast can write a small, redacted support bundle for bug reports. It records the version, platform, tool versions (FFmpeg, catt), recent errors and the in-app activity log, while masking LAN IP addresses and reducing absolute paths and the home directory to basenames. Credential-like settings keys are redacted. The bundle is bounded to 256 KiB and written owner-only (0600).

```sh
smoothcast --diagnostics            # writes ~/.config/cast-control/diagnostics-<UTC>.json
smoothcast --diagnostics /tmp/sc.json
```

The same bundle is available from the app menu under **Save diagnostics…**. It works without GTK, a display or a working virtual environment, so it is usable even when setup has failed.

## License

MIT
## Configuration robustness

Saved preferences are validated separately for each key. If a configuration
contains a null recent-file list, a nonnumeric gain or an unknown audio profile,
SmoothCast falls back only for the invalid field and preserves valid neighbours.
Collection sizes and numeric ranges are bounded; nested defaults are copied
for each load. Reading the file never overwrites the user's original settings.
Implementation: GTK-independent `src/config_control.py`.

## Issues and improvement planning

**All unfinished features, regressions, device qualification and suggested
improvements live in [GitHub Issues](https://github.com/gmanldn/smoothcast/issues).**
There is no root Markdown backlog. Use the original `SC-001`–`SC-132`
identifiers to find migrated proposals and the `[P0]`, `[P1]` or `[P2]`
prefix to prioritise them. Items with code implemented but pending physical
TV/OS verification deliberately remain open.

The complete [issue workflow, provenance and historical recovery guide](docs/ISSUES.md)
explains where issues are stored, how to claim and verify them, and how to
preserve earlier research. Agents should start with
`python3 scripts/ticket_digest.py --next`, a bounded read-only index rather
than a second backlog. Contribute a new improvement using the
[GitHub issue template](https://github.com/gmanldn/smoothcast/issues/new/choose),
not by adding a second TODO document. Issue branches and pull requests target
`develop`; `main` is protected and receives release merges only.
