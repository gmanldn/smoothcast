# SmoothCast

A modern GTK4/libadwaita Chromecast companion with live compressor metering, dialogue auto-fix, and zero flicker.

## Why SmoothCast

**The tool that plays your media on every screen in the house, and lets everyone in the room join in.**

- **Everyone's hands on the queue, nobody installs anything.** Guests scan a QR code, join with their name and add songs and films from their own phone, vote, reorder and control playback. No app, no account, no cloud.
- **Every device is a screen.** Open the room's `/screen` page on a TV, tablet, laptop or spare phone and it becomes a display or speaker for the shared queue. Chromecast, DLNA TVs and browsers all appear as targets; formats a browser cannot play are converted on the host automatically.
- **Host or client, your choice.** A computer with the media runs SmoothCast as the host; every other device only needs a browser. Several hosts can coexist on one network.
- **Bullet-proof by design.** Fenced, idempotent commands; stale or double taps cannot skip a film; a failing guest, screen or receiver never interrupts what is playing; recoveries are automatic and every failure is explained in plain words.
- **Built for the home network.** Everything stays on your LAN and is never reachable from the internet. Anyone you've given the Wi-Fi password is trusted to join; joining is open by default, with an optional House PIN for untrusted Wi-Fi. Sessions expire and the host can sign everyone out at any time.

See [what makes SmoothCast different](docs/PRODUCT.md) for the roles and guarantees, and the [vision](docs/VISION.md) for where it is going: one smart mesh of media nodes, web clients and casting targets, controlled as one, with a shared queue.

## Features

- **Screens: any browser is a display or speaker** — a paired phone, tablet, laptop or smart-TV browser opens `/screen` and plays the shared queue on itself, with direct play when the browser supports the format and a bounded, nice'd FFmpeg conversion when it does not; the host can disable guest screens in Preferences > Playback > Shared room (see [Screens](docs/LAN_PORTAL.md#screens-browsers-as-playback-targets))

- **Live compressor metering** — DJM-style segmented LED meters showing input/output levels and pump/gain reduction in real time, with smooth attack/release ballistics (no flicker); bounded metadata memory for long films and asynchronous FFmpeg shutdown
- **Dialogue auto-fix** — automatic input trim that drives the compressor to always engage, plus acompressor + limiter chain that keeps dialogue audible over action scenes
- **Night mode** — stronger compression for late-night low-volume viewing
- **Dialogue-first surround downmix** — with the Dialogue or Night profile, 5.0/5.1/6.1/7.1 and quad tracks are mixed to stereo with the centre channel lifted ~5 dB over FFmpeg's default matrix, surrounds lowered, the LFE dropped and no clipping; the level used for auto-trim is measured on that same mix. Original, stereo/mono and unrecognised layouts keep the plain `-ac 2` downmix
- **Live position tracking** — seek bar stays on the original film timeline through pause/resume, seeks and 0.5×–2× playback; HLS time is converted to source time
- **Shared room with optional House PIN** — everyone on the local network can join with their name, see who is present, add videos to the shared queue, vote, reorder/remove/play titles, and control play/pause, skip, seek and volume from a phone
- **Responsive window** — sizes itself to the monitor, stacks cards as the window narrows, wraps playback buttons, and scrolls the full page vertically rather than clipping
- **Refined media-console interface** — purpose-built Now Playing slate, primary Open video action, readable transport controls, compact queue and activity empty states, live device badges, grouped sound/video/subtitles settings and structured technical diagnostics
- **Desktop notifications** — posts a Gio notification when a cast finishes, fails or the receiver disappears, but never while the window is focused; Preferences > Playback > Notifications turns it off and the choice is stored as `"notifications"` in `config.json`
- **Fullscreen idle chrome** — hides the header bar after ~2.5 s without input while fullscreen and focused, then restores it on pointer motion, key presses, focus or accessibility changes; leaving fullscreen always restores the chrome
- **Audio-only queue and casting** — MP3, AAC/M4A, FLAC, Ogg/Opus, WAV and AIFF files are probed and queued with duration and codec details; Google Cast uses an AAC-only HLS transcode path with no placeholder video
- **HLS transcoding** — Linux VAAPI H.264 encoding with a bounded software fallback for video; macOS/Windows start with software libx264; audio-only sources skip video planning and encoding; selects the LAN source IP routed to the Chromecast
- **Direct play** — untouched passthrough for compatible files; playback speed/rotation automatically switch to the transcode path
- **Remote URL casting** — Open URL validates HTTP(S) addresses and calls catt asynchronously; known site pages (YouTube, Vimeo and similar) are rejected with an actionable "paste a direct media URL" message instead of being claimed as supported, and invalid URLs or device errors are reported instead of treating the URL as a local file
- **Subtitle support** — load an explicit .srt/.vtt/.ttml file, auto-match sidecars, choose an embedded MKV text track, or burn captions into H.264 video
- **Loudness normalisation (optional)** — EBU R128 programme (-16 LUFS) or album (-18 LUFS) targets with true-peak limiting (-1.5 dBFS) for transcoded audio; off by default, configurable in the Playback settings card, and never changes system volume
- **Searchable queue** — Ctrl+F filters filenames and folder paths. Drag a row by its handle or use the arrow buttons to change playback order. Save the queue as an M3U playlist to keep that order for later.
- **Queue / Up Next and repeat-one** — advance or loop when the TV reports completion; old stream cleanup finishes before restarting
- **Reliable M3U playlists and resume** — atomic save/load, deduplication and missing-file handling; remembered positions never override an explicit rewind
- **Keyboard shortcuts and capture** — GTK4-compatible fullscreen, working Clear recent files action, and non-blocking, collision-safe FFmpeg screenshots (always-on-top is compositor-controlled)

## Release packages — PyInstaller

**PyInstaller is the canonical release packager** for native SmoothCast desktop
bundles. Existing Python-first setup scripts remain source/developer installation
paths. See the [packaging guide](docs/PACKAGING.md) for build requirements,
platform qualification, checksums and headless artefact checks. A Python wheel
is not a native desktop release, and unsigned CI builds still require real-device
qualification.

## Install — Python-first, all three desktops

**No preinstalled Python is required.** Each platform script probes for Python 3.10+ and acquires it automatically when missing (Linux distro package manager, macOS Homebrew, or Windows WinGet/verified python.org installer). Setup then installs GTK4, libadwaita, PyGObject, FFmpeg/ffplay/ffprobe and all declared Python dependencies. Native package provisioning needs Internet access and may require OS administrator or Apple Command Line Tools approval.

| OS | Setup command | Application shortcut |
|---|---|---|
| Debian/Ubuntu, Fedora, Arch | `bash setup/linuxsetup.sh` | Linux application menu / GNOME dock |
| macOS | `bash setup/macsetup.sh` | `~/Applications/SmoothCast.app` |
| Windows 10/11 x64 | Double-click `setup/winsetup.bat` | Windows Start Menu |

The three scripts delegate to the same stdlib-only `setup/bootstrap.py`. They **ask where to install** the application, defaulting to a per-user program folder (or the last successful choice), copy only application files and provision an isolated `.venv` there. Use `--install-dir "<path>"` for a specific location, `--yes` to skip the prompt, `--check` for read-only diagnostics or `--no-shortcuts` to skip desktop integration. Linux adds an XDG icon/menu entry; macOS registers `~/Applications/SmoothCast.app` with a real ICNS icon; Windows creates a branded Start Menu shortcut. See [setup/README.md](setup/README.md) for dependencies, recovery and limitations.

The single `./smoothcast` launcher is a Python script that runs on Linux, macOS and Windows (use `python smoothcast` on Windows). It bootstraps a project-local `.venv` when needed, then hands off to the GTK runtime. Version lookup remains side-effect free: `./smoothcast --version` (Unix), `python smoothcast --version` (Windows), or `python src/version.py` (any OS).

**Cross-platform status:** Linux is the existing working implementation. The Windows and macOS native setup/bootstrap paths are now implemented and covered by portable tests, but have **not** yet passed end-to-end GUI and Chromecast tests on those machines. Windows uses MSYS2 UCRT64, whose Python extension packaging differs from official CPython; the `catt` installation may require follow-up dependency work. Both systems initially use software libx264 rather than Linux VAAPI. See the dated [platform status matrix](docs/PLATFORM_STATUS.md) for the current CI evidence and unverified native checks.

### FFmpeg compatibility

SmoothCast requires **FFmpeg 5.0 or newer** for its HLS encoding and
MKV decoder pipeline: it uses `-readrate` and the scale filter's
`force_divisible_by` option. A fast, bounded `ffmpeg -version` check runs
off the GTK thread **before any existing receiver is stopped** for a new
cast or HLS restart. An outdated, missing, hung or unrecognised FFmpeg build
produces an actionable error rather than a partially started stream.
The normal platform setup scripts provision FFmpeg; if your distribution
ships an older release, upgrade the FFmpeg package before casting.

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
entry labelled **DLNA · TV name · IP** in the receiver menu next to **Cast to TV**, then press **Cast to TV**.
The application supplies a temporary HTTP URL with an unguessable token and
byte-range requests; the TV fetches a progressive MP4 from your machine.
Playback, pause, stop, seek and optional volume controls use UPnP SOAP, **not**
the Google Cast backend. A receiver must advertise a compatible DLNA
AVTransport service; some TVs with only UPnP *media browsing* are not
MediaRenderers and will not be listed.

If a receiver reports HTTP media formats through ConnectionManager, SmoothCast
checks that the list allows MP4 before replacing an active cast. Receivers that
return no usable format information can still use the normal MP4 path.

For compatible H.264/AAC MP4 files, DLNA playback starts directly. An MKV
with compatible tracks is remuxed to a temporary MP4; incompatible codecs,
non-default audio tracks or selected subtitles require full FFmpeg
transcoding and burn-in **before playback starts**. With Dialogue or Night
selected, known surround layouts are mixed to stereo with extra weight on
the centre channel and no LFE contribution. For long films preparation can
take significant time and disk space (roughly twice the source-file size must
be available). The application checks local free space, refuses a conversion
larger than the scratch cap (`cache_cap_mb` in `~/.config/cast-control/config.json`,
default 8192 MB, `0` = unlimited) before FFmpeg starts, sweeps scratch left by a
crash (`smoothcast-dlna-*` in the system temp directory, once older than 10
minutes) at the next startup, and reports conversion errors. FFmpeg runs at below-normal priority (nice 10 on Linux/macOS, `BELOW_NORMAL_PRIORITY_CLASS` on Windows) so the desktop stays responsive during software encodes; set `"lower_ffmpeg_priority": false` in the same config file to opt out. The DLNA target path currently uses normal playback speed, no video
rotation and the original sound profile; Chromecast still supports its own
transcode and audio processing. SRT/ASS burn-in on DLNA depends on libass
support in your FFmpeg build.

The DLNA media HTTP listener binds only to the specific private LAN IPv4
interface routed to the selected receiver, never all interfaces. An invalid,
missing or unbindable local interface prevents a new cast and does not stop
another receiver's playback; loopback binding is used only by isolated tests.
Receiver IP and an unguessable per-session URL still restrict requests.
HTTP/1.1 requests also require a Host header matching the bound interface
(optionally including the port), so a malicious Host cannot use DNS rebinding
to fetch the film. Duplicate/mismatched Host headers are rejected; optional
HTTP/1.0 Host is retained for older DLNA devices. Connections time out after
15 seconds without socket activity, and oversized byte-range headers return
HTTP 416 without parsing unbounded integers. These guards do not replace
real-device protocol qualification or the remaining HLS hardening work.

DLNA discovery currently requires private IPv4 SSDP responses with a matching
HTTP device-description host. VPNs, Wi-Fi isolation and firewall rules may
prevent discovery or TV-to-computer HTTP connections. Stopping SmoothCast
also stops its private DLNA HTTP server, even if **Keep streaming** is enabled.

Each DLNA scratch directory has a process-held exclusive lease. FFmpeg inherits
that lease, so a concurrent SmoothCast startup never deletes an old-but-active
conversion or playback file. A crashed session's directory is reclaimed after
the stale-age threshold only once its lease can be acquired. Legacy directories
without a verifiable lease are kept rather than risking another active
instance's film. Windows inherits the lease handle through the explicit process
handle list and only sweeps the current user's LocalAppData `Temp` directory;
custom or shared Windows temp roots fail closed and remain untouched.
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
transcoded picture. PGS, VobSub and DVB bitmap tracks are decoded by FFmpeg
and overlaid with their authored palette and cue timing; they use software
encoding. Forced-only and multilingual tracks follow the same per-film and
language-preference rules as text tracks. Unknown subtitle formats fail with
a visible error instead of silently proceeding with another track. Bitmap
placement has not been qualified on physical receivers.

**Audio delay (lip-sync):** if the sound is ahead of or behind the picture, use
**Audio delay (lip-sync)** in the main menu, or press **Shift+G** (sound 50 ms
earlier) / **Shift+H** (50 ms later); *Reset delay* clears it. The offset is
limited to ±5 s and is remembered per film. While casting over HLS or DLNA the
stream restarts at the current position. A non-zero delay needs a transcode
(DLNA re-encodes the audio), so it is not applied to direct play; the saved
value is used on your next cast. The FFmpeg arguments are covered by
`tests/test_audio_delay.py`; it has **not** been verified on a physical
receiver yet.

**Subtitle delay:** if captions run early or late, use **Subtitle delay** in
the main menu, or press **G** (100 ms earlier) / **H** (100 ms later); *Reset
delay* clears it. The offset is whole milliseconds, limited to ±30 s, and is
remembered per film. While casting over HLS or DLNA the stream restarts at the
current position so the new timing is burned in. A non-zero delay always burns
captions into the picture (a Cast receiver cannot time-shift a sidecar track),
so it needs the slower transcode path and is not applied to direct play; the
saved value is used on your next cast instead. Burn-in timing is checked with
real FFmpeg renders in `tests/test_subtitle_delay.py`; it has **not** been
verified on physical receivers yet. Streams resumed or seeked to a later
position also now draw burned-in captions at the correct film time. Bitmap
subtitle rendering uses FFmpeg's bitmap-subtitle video input to the overlay
filter; check that the installed FFmpeg build includes the needed decoder.

**Subtitle style:** set `"subtitle_style"` in the config file to `large`,
`high-contrast` (bold, on a translucent box) or `raised` (higher margin, clear
of overscan); `default` changes nothing. A preset burns captions into the
picture, so, like a delay, it needs the transcode path and applies from your
next cast or restart. It is applied only to plain-text subtitles (SRT, WebVTT,
embedded SubRip/mov_text); ASS/SSA keep their own authored styling. Presets are
checked with real libass renders in `tests/test_subtitle_style.py`. Styling
presets apply to text subtitles; bitmap captions retain their encoded palette
and placement. Choose a preset in **Preferences → Sound & subtitles → Captions**
or set the config value directly. Physical receivers have not been qualified.

### Language preferences

Set preferred audio and subtitle languages once in `~/.config/cast-control/config.json` and SmoothCast applies them to every film that has no explicit per-file track choice:

```json
{
  "preferred_audio_languages": ["ja", "en"],
  "preferred_subtitle_languages": ["en"],
  "language_overrides": {"some show": {"audio": ["fr"]}}
}
```

Languages are ISO 639-1/2 codes or English names (`en`, `eng`, `English`, `pt-BR`). The first preference with a matching audio track wins; commentary and audio-description tracks are used only if nothing else matches. **Forced** captions (foreign-language dialogue only) and **full** subtitles are handled separately: when the chosen audio is already in a preferred subtitle language you get that language's forced track, or no subtitles if it has none; when the audio is in another language you get the full track in your first matching language. If no preference matches, or none is set, the previous behaviour applies unchanged (the file's default audio; forced, then default, then English subtitles). An override applies to files named like `Some.Show.S01E02.mkv` and replaces only the lists it sets; files without an episode marker are films and never match one. A track you pick by hand always wins; supported bitmap tracks (PGS, VobSub and DVB) participate in the same preference rules. There is no Preferences control yet: edit the file.

### Automatic crop and deinterlace (opt-in)

Two detectors can clean up the picture before it is encoded for the TV. Both are **off by default** because detection adds a few seconds to a cast start. Turn them on in **Preferences > Playback > Picture and delivery** (the **Check this film** row there previews what each would do to the selected film, for example "crop to 1920×800 (removes 26% of the picture)", without changing anything), or in `~/.config/cast-control/config.json`:

```json
{"auto_crop": true, "auto_deinterlace": true}
```

`auto_crop` samples three short windows with FFmpeg's `cropdetect` and crops only when most samples agree on one even, in-frame rectangle that removes at least 2% of the picture and keeps at least 40% of it (so dark scenes never produce a bad crop). `auto_deinterlace` runs a short `idet` field analysis and applies `yadif` only when most frames are interlaced **and** share one field order, so progressive video is never blurred. Detection is bounded (12 s per pass), cached per file so seeks and retries are free, and any failure means no filter is applied. The filters run before subtitles are burned in, apply to HLS and DLNA transcodes (not direct play or a copied DLNA stream), and make a hardware encode download frames to the CPU for the filter. Tests that run real FFmpeg on synthetic clips are in `tests/test_video_policy_ffmpeg.py` (set `SMOOTHCAST_REAL_FFMPEG=1`; CI does).

## Interface and visual design

**Window layout.** The player is always the main thing: title and state, preview, one seek bar with elapsed and remaining time, transport (previous, −30/−10, play, +10/+30, next, stop), volume with a captions toggle, the **receiver menu** and the **Open media / Cast to TV / Play locally / Stop TV** actions. The receiver menu sits directly above the Cast button and shows a green or red edge for an online or offline receiver. Everything else lives in one tabbed **side panel** (switch with **Alt+1** – **Alt+5**):

| Tab | Contents |
| --- | --- |
| **Queue** | Up next with a count badge: add media or music, search (**Ctrl+F**), drag or arrow-reorder, auto-play next |
| **Devices** | Receiver status, scan again, add a receiver by IP, connection check, read-only network activity (a `!` badge means no receiver is chosen or it is offline) |
| **Room** | Shared-room address, QR code, PIN, guests, access reset |
| **Settings** | Video quality, sound, loudness, subtitles, direct play (and **All preferences…**) |
| **Info** | Stream diagnostics, buffer-health graph, audio signal meters, activity log |

At **940 px** and wider the side panel sits beside the player and scrolls on its own; below that it stacks under the player (the tab strip then shows icons only under 400 px). Above 1000 px the player stops growing so the seek bar and buttons stay readable. Wrapping decisions use the *measured* width of the transport controls and the player's measured height, so a larger font wraps earlier and the whole player, including **Cast to TV**, stays on screen instead of scrolling: the preview picture shrinks first. The window's minimum width at every size is below the width it is chosen at, so it can always be shrunk until it stacks (`scripts/gui_checks.py side-panel` checks this with real widgets).

**Accent colour.** Preferences > Appearance > Accent colour offers seven presets (Default blue, Teal, Green, Amber, Orange, Rose, Violet) that recolour suggested-action and play buttons, sliders, checked switches and the current queue row, live and without a restart. Every preset is checked for accessibility: button text reaches at least 4.5:1 contrast on the accent and its hover shade (the text colour, dark or white, is calculated from the accent), and the accent itself reaches at least 3:1 against the app surfaces. The choice is stored as `"accent"` in `config.json` (a corrupt value falls back to the default). It is an extra stylesheet layered over SmoothCast's own; the system GTK theme is never edited, and **Default blue** removes the override entirely.

**Interface density.** Preferences > Appearance > Interface density offers Compact, Comfortable (the default, exactly the stylesheet as designed) and Spacious. It scales page margins, column spacing, the preview height, card and chip padding, and the sizes of the play, transport and action controls, live and without a restart; control rows wrap earlier at larger densities instead of being clipped. The choice is stored as `"density"` in `config.json` (a corrupt value falls back to Comfortable). **No clipping at 360 px or under large fonts:** in windows narrower than 1000 px, long labels wrap and captions inside buttons ellipsize instead of raising the window's minimum width. Measured with real widgets (`scripts/gui_checks.py`), the 360 px layout stays within 360 px at every density with 14, 18 and 22 pt interface fonts (without this the minimum was 624 px at 22 pt). Wide windows are left exactly as designed.

**Preferences:** choose **Preferences…** from the main menu, use **Ctrl+,**,
or select **All preferences…** in the **Settings** tab. A searchable,
native libadwaita window groups Picture and delivery, Queue behaviour, Audio,
Captions and Appearance with per-setting explanations and explicit notes about
when a new cast or encoder restart is required. The side panel's **Settings**
tab shows the everyday quality, sound and caption controls directly.
Both views edit the same saved preferences through the existing callbacks.
Film-specific audio/embedded caption tracks are only enabled when available.
No settings operation contacts a TV merely by opening the window.

This follows GNOME's guidance on [adaptive layouts](https://developer.gnome.org/hig/guidelines/adaptive.html),
[application preferences](https://developer.gnome.org/hig/patterns/controls/menus.html)
and [GTK main-thread ownership](https://docs.gtk.org/gtk4/section-threading.html).

SmoothCast uses a consistent midnight-blue GTK4 palette, 14px base text, higher-contrast secondary labels, a contextual primary action (Open before selection, Cast afterward) and compact technical panels. The local preview shows real decoded frames while scrubbing and an embedded video player on Play; a metadata slate is retained as the empty or decode-error fallback. The queue shows a purposeful empty state and becomes scrollable only when there is content. The Devices tab distinguishes a Chromecast found on the network from one confirmed reachable by a status query. Playback settings are grouped by function; diagnostics show separate playback/encoder and media/output sections. The Info tab also keeps a bounded 60-second buffer-health graph: measured buffer-ahead (area), available HLS segments (line) and watchdog restart marks (red), sampled from the existing half-second tick without extra polling.

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

If VAAPI stalls and the software retry then succeeds, SmoothCast records that in `~/.cache/cast-control/hw_encoder.json` (keyed by the ffmpeg binary, render device, DRM driver and kernel, expiring after 14 days) and skips the 15 s hardware wait on later casts; upgrading ffmpeg or the kernel re-probes automatically, and `smoothcast --reprobe-encoder` clears the record. The volume measurement used for dialogue auto-trim is cached per file (size/mtime) and audio track, so retries and seek restarts do not repeat it. Speed and rotation selections are preserved if the VAAPI encoder stalls and restarts with the software encoder. For faster/slower playback, FFmpeg reads input at the selected speed (`-readrate`) while rescaling video and audio presentation timestamps. The seekbar, saved position and live device/encoder feedback remain in source-video seconds. Changing speed during direct play transparently starts a transcode of the selected video.

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

## Command-line control (headless)

Control a **Chromecast** without opening the GUI — no display, GTK or desktop session is needed, so it works over SSH and in scripts:

```sh
smoothcast cast Film.mkv -d "Living Room"            # direct play if compatible, else transcode
smoothcast cast Film.mkv -d 192.168.1.50 --offset 1:02:03 --subs Film.en.srt
smoothcast pause|resume|stop -d "Living Room"
smoothcast seek 1:30 -d "Living Room"                # seconds, MM:SS or HH:MM:SS
smoothcast status -d "Living Room" --json
```

Give the receiver with `-d/--device` (name or IPv4) or the `SMOOTHCAST_DEVICE` environment variable. `cast` also takes `--mode auto|direct|transcode`, `--quality`, `--audio`, `--no-subs` and `--title`; it replaces any earlier SmoothCast-owned cast and leaves the stream running after the command returns. `stop` also ends SmoothCast's own encoder, server and catt processes for that cast. Seeking a live transcode restarts the encoder at the new position with the same settings, as the application does.

`--json` prints exactly one object: `{"ok": true, "command": "status", "state": "PLAYING", "position": 65.0, ...}` or `{"ok": false, "command": "pause", "error": "failed", "message": "..."}`; human-readable output goes to stdout on success and errors to stderr.

| Exit code | Meaning |
| --- | --- |
| 0 | success |
| 1 | the operation failed (receiver or catt refused it, or the cast did not start) |
| 2 | usage error: bad arguments, time or no receiver given |
| 3 | receiver unreachable or offline |
| 4 | media problem: file missing, unreadable or unsupported |

DLNA renderers are not supported from the command line yet, and a real-receiver check of these commands is device-pending. Portable tests run them against mocked receivers.

## Local control API (opt-in, for Home Assistant and scripts)

A small headless HTTP API controls a Chromecast without the GUI. It is **off by default**: nothing listens until you run it yourself, and it never imports GTK.

```sh
smoothcast --control-api token          # creates ~/.config/cast-control/control_api_token (0600) and prints it
smoothcast --control-api serve          # 127.0.0.1:8800, casting disabled
smoothcast --control-api serve --bind 192.168.1.20 --port 8800 --media-root ~/Videos
```

Security: every request needs `Authorization: Bearer <token>` (compared in constant time; the token may also come from `SMOOTHCAST_CONTROL_TOKEN`, at least 16 characters). `--bind` accepts only loopback or a private LAN IPv4 address, never `0.0.0.0` or a public one. No CORS headers are sent, so web pages cannot call it. `POST /v1/cast` is refused unless `--media-root DIR` is given, and then only files inside those directories (after resolving `..` and symlinks) can be cast. Request bodies are limited to 64 KiB, one receiver command runs at a time, and the server logs method, path and status only, never tokens. It speaks plain HTTP: keep it on loopback or a trusted LAN, or put a TLS proxy in front.

| Endpoint | Body or query | Result |
| --- | --- | --- |
| `GET /v1/health` | none | `{"ok": true, "version": "v1.0.60"}` |
| `GET /v1/status?device=NAME` | `device` | state, position, duration, title, volume, muted, session |
| `POST /v1/pause`, `/v1/resume`, `/v1/stop` | `{"device": NAME}` | `{"ok": true, ...}` |
| `POST /v1/seek` | `{"device": NAME, "time": 90 or "1:02:03"}` | new position and method |
| `POST /v1/cast` | `{"device": NAME, "file": PATH, "mode", "offset", "subs", "no_subs", "quality", "audio", "title"}` | stream details |

Errors return `{"ok": false, "command", "error", "message"}` with HTTP 400 (bad request), 401 (token), 403 (cast not allowed or outside the media roots), 404, 405, 413, 422 (media), 502 (receiver refused) or 503 (receiver unreachable). `device` is a receiver name or IPv4, exactly as for the command line; DLNA renderers are not supported yet. Example: `curl -H "Authorization: Bearer $TOKEN" -d '{"device": "Living Room"}' http://127.0.0.1:8800/v1/pause`. A real-receiver check is still pending; the API is covered by portable tests with fake handlers.

## Shared room

The desktop app starts an authenticated, browser-based shared room while it is
running. The main screen shows a friendly mDNS address such as
`smoothcast-lounge.local` (with the numeric IP as a fallback). Joining is open
by default on the trusted home LAN: enter a display name and you appear in the
presence list, able to add videos to the shared queue, vote, reorder or remove
titles, start a film, skip forward/back and use play/pause, seek and volume. An
optional **House PIN** can be enabled in Preferences when people you do not
trust use the Wi-Fi. The queue belongs to the running desktop queue; web
actions are marshalled onto the GTK thread. The portal uses the Python standard
library and adds no web framework dependency. It stops with the app and
restarts with a new PIN if the selected LAN interface changes. See the
[shared room guide](docs/LAN_PORTAL.md) for joining, security and verification
details.

## Playlists, resume and safe playback transitions

**Save playlist** writes an atomic local `smoothcast_playlist.m3u` under your home directory. **Load playlist** accepts M3U comments and relative paths, skips missing/unavailable entries and removes duplicates without changing the Loop setting. The Loop menu action independently toggles repeat-one.

Opening a previously watched video can resume from its saved position. An intentional jump to **00:00** always goes to the start; automatic Up Next also starts the next film at zero. Direct Chromecast playback seeks to the remembered position, falling back to the transcoder if the receiver cannot seek.

When one film finishes, the UI holds incoming cast commands until the old server and HLS files have been cleaned up, avoiding overlap between sessions. Once the TV reports that a movie ended, cleanup does not send an unnecessary second Stop command that might interrupt other playback.

**Bookmarks** save named positions in the current local film. They survive restarts and file moves because each marker is tied to a SHA-256 content fingerprint rather than the path; opening a bookmark on different media is refused. Use the **Bookmarks** menu to add a marker at the current position, jump to a saved marker, or clear all markers. Bookmark names and positions are bounded and validated when configuration is loaded.

## Responsive sizing

The application no longer requires fullscreen or a 1400-pixel-wide minimum window. Saved startup dimensions are bounded by the detected monitor's logical geometry, leaving space for decorations. Layout automatically reflows on resize: **940+ logical px** puts the player beside the tabbed side panel; narrower widths stack the panel under the player. Transport controls wrap into two symmetrical rows, the action buttons flow into two columns, preview height and card padding become more compact, and one outer vertical scroller keeps everything accessible even when the window is shorter than the full interface. Resizing wider restores the side-by-side layout. The app avoids shrinking controls to unreadable sizes.

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
Running `./smoothcast` from this directory bypasses any old dock entry.
A dependency repair now installs from `pyproject.toml`, not a missing
`requirements.txt`; repair failures print the actual error rather than
pretending that the same release installed again.

If the menu entry is missing despite a successful read-only check, log out and back in to refresh GNOME's application cache. To diagnose a user-initiated launch failure (not an automated test), run `./smoothcast` from the same checkout in a terminal; on GNOME, inspect `journalctl --user -b`. Do not use `sudo` for desktop integration because it would install the icon under root's account.

A second launcher click raises the existing window rather than silently exiting. On KDE or other docks, if an old pin remains stale, remove it and pin the new **SmoothCast** entry once. Regression tests: `python3 -m unittest discover -s tests -v`.

## Desktop media controls (MPRIS2)

On Linux, SmoothCast publishes an MPRIS2 player (`org.mpris.MediaPlayer2.smoothcast`) on the session bus, so the desktop's media widget and media keys (play/pause, next, previous, seek) control the current cast without focusing the window. Metadata (title and length) and the live position are exposed. Another application's cast is never controlled: when SmoothCast does not own playback the player reports `Stopped` and exposes no controls. MPRIS2 is Linux-only and best-effort — a missing session bus is ignored, and the application runs normally. The mapping is covered by portable tests with a fake bus plus one real private-`dbus-daemon` round trip; a desktop media-widget check is still pending.

## Streaming reliability and local-network safety

HLS HTTP/1.1 requests require a Host header matching the exact listening
interface IP (loopback or the receiver-routed LAN address), optionally with
the port. Duplicate or mismatched Host headers return HTTP 400 to prevent
DNS-rebinding attacks. Old HTTP/1.0 clients may omit Host. Handler sockets
have a 15-second inactivity timeout to prevent idle clients from indefinitely
occupying a thread. Keep the receiver allowlist and per-generation token as
separate security controls. Physical Chromecast qualification is still needed.

The HLS server prefers port 8767 (set `"hls_port"` in `config.json` to use another, 1024–65535). If another program holds that port SmoothCast uses the next free one in 8767–8798, passes it to the server, the stream URL and `session.json`, and reuses a kept-alive SmoothCast server wherever it is listening; if every port is taken the cast fails with a clear error. `smoothcast --network-check` probes the port of the active stream. The server listens on its port for Chromecast access, but **only on loopback plus the single LAN interface chosen for the receiver's route — never `0.0.0.0`** — and answers `403 Forbidden` to every client except the receiver and loopback (loopback keeps `/_smoothcast/health` working). The allowed receiver and the **active stream generation** (a random 128-bit token in the playlist and segment names) are published in `~/.cache/cast-control/server_access.json` before each cast and re-read per request, so a server kept alive by *Keep streaming* follows the new receiver; a kept server bound to a different interface is replaced only after its PID is verified as SmoothCast's own, otherwise the cast is refused with an actionable error. IPv4-mapped IPv6 clients are judged by their IPv4 address, public addresses are never allowed, and when the receiver's address is unknown (a cast selected by name) only private-LAN clients (RFC 1918 / link-local) are accepted. A real Chromecast must still be confirmed to play the stream (device-pending). It serves only the active generation (`movie-<token>.m3u8`, `segment-<token>-N.ts`): any other token, a previous cast's URL and the old fixed `/movie.m3u8` name get 404, and stopping a cast revokes its token. HLS media responses are HTTP/1.1 with `Accept-Ranges`, ETag/Last-Modified validators, single or suffix byte ranges (206 with an exact `Content-Range`) and RFC 7233 `416` + `Content-Range: bytes */len` for invalid or unsatisfiable ranges. It exposes only the generated playlist and segment media. Internal `session.json`, logs, staged subtitles, and directory listings are inaccessible. HLS responses omit cross-origin wildcard headers; native receiver playback must be qualified on hardware. SmoothCast checks a dedicated health endpoint before reusing a server; a port conflict produces an actionable error instead of silently streaming from the wrong process. Failed startup or seek-restart attempts clean up child processes, and restored sessions verify Linux PID ownership before terminating saved processes.

Run `python3 -m unittest discover -s tests -v` for the desktop, HTTP server and streamer regression tests.

## Sleep timer

The Sleep timer menu now stops the active SmoothCast session after the selected interval (15–60 minutes). The deadline is saved across application restarts, and can be cancelled with **Off**. The application must remain running for the timer to fire; closing it with Keep streaming enabled does not leave a background scheduler running.

On a Google Cast receiver the volume fades out over the last `sleep_fade_seconds` (default 30, `0` disables, maximum 600; set in `~/.config/cast-control/config.json`) before playback stops. The receiver's original volume is read once at the start of the fade and restored after the cast has stopped, or immediately if you cancel or re-arm the timer; changing the selected receiver abandons the fade without touching the new one. A receiver whose volume cannot be read is left alone. DLNA renderers are not faded (no readable volume), and a crash or force-quit during a fade leaves the volume lowered until you raise it.

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

The **window title** always shows the version of the **running** SmoothCast process; **About** uses exactly the same value. If an external installation or checkout operation changes the on-disk release while SmoothCast remains open, reactivating or focusing the window displays an explicit **installed versus running** notice. Python modules are never hot-reloaded; finish playback, quit and relaunch before relying on the new code.

CI includes `tests/test_version_integrity.py` to check the canonical source, CLI output, UI wiring and documentation; do not maintain a second hardcoded "Current: X.Y.Z" version elsewhere.

## Safe, opt-in update checks

By default **SmoothCast makes no Git update request at startup**. Under **Preferences → Appearance → Updates**, users can opt into **Check for releases on startup**, effective on the next launch. This performs a bounded, read-only Git fetch **after** the first window is interactive and only for clean Git checkouts on the released `main`/`master` branch. Development branches, dirty worktrees, frozen apps and installed non-Git releases are never changed. If an eligible newer semantic release is found, the application displays its candidate version and the running version **without installing it**. It never modifies loaded application files, calls `git pull`, or restarts a cast.

**Require a trusted signature** is enabled by default for update discovery. Verification uses `git verify-commit` or a matching signed release tag against keys **the user has explicitly imported** into their own GPG keyring. An unverifiable candidate is reported as **untrusted**, not installed. The target SHA comes from an explicitly fetched origin release-branch ref; unrelated fetched tags cannot substitute a different candidate. This is not an automatic update installer: install from your trusted distribution channel when playback has finished, then quit and relaunch. The transactional, signed, one-click install/restart workflow remains tracked in [#138](https://github.com/gmanldn/smoothcast/issues/138).

The advanced configuration keys are `"check_release_updates": false` and `"verify_updates": true`. The old `"auto_update"` key is **ignored**, even if an older installation saved it as `true`: a new, explicit opt-in is required for any update-network check. An opted-in running app performs **discovery only**, not automatic installation. `--self-test` is isolated and never checks the network.

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
python3 -m compileall -q src scripts setup tests
ruff check src scripts setup tests smoothcast setup.py
python3 -m pytest -q tests   # full lane: MINOR/MAJOR bumps only
```

Patch progress takes the fast lane; the full portable suite is required only
for MINOR/MAJOR releases. CI applies the same policy via
`scripts/ci/test_scope.py`. These commands do not launch SmoothCast or bring an
existing window to the foreground. Pytest marks its subprocesses with a GUI
refusal flag, and direct `--self-test` on the normal launcher is refused before
bootstrap.

Opt-in, outside pytest: `python3 scripts/gui_checks.py` runs real GTK widgets through first-run receiver choice, a saved device and Help > Report a problem inside a private Xvfb session (private XDG directories, no session bus, no LAN scan, no receiver contact, browser launch patched). It needs Linux with `xvfb`, `xauth` and GTK 4/libadwaita, and prints one PASS/FAIL line per check.

**Version coverage:** On the full lane, GitHub Actions runs the **entire**
portable pytest suite and Python syntax check using both Python **3.10** (the
published minimum) and Python **3.13** (the primary development interpreter). Unlike bare
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

The same bundle is available from the app menu under **Save diagnostics…**. **Report a problem…** (same menu) opens a prefilled GitHub bug form in your browser with only the SmoothCast version and a coarse operating-system label filled in; nothing is sent by the app, and you attach the saved diagnostics file yourself. It works without GTK, a display or a working virtual environment, so it is usable even when setup has failed.

The bundle records the active receiver's **protocol and model** (no address or name) so reports are comparable. To share how SmoothCast behaves on your TV or Chromecast, use the **Device compatibility report** issue form; results are collected in [docs/DEVICE_COMPATIBILITY.md](docs/DEVICE_COMPATIBILITY.md).

The HLS server also keeps a **bounded `server.log`** in `~/.cache/cast-control/` (same size limits as the error log) recording failed requests (403/404), startup and bind failures; successful requests are not logged. Its redacted tail is included in the diagnostics bundle under `server_log`.

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
not by adding a second TODO document. All work is committed directly to
`develop`; `main` is release-only and is updated automatically by a develop→main
pull request when a verified `develop` commit bumps `src/version.py`.
