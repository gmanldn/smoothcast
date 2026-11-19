# SmoothCast architecture — open the relevant module

SmoothCast is Python 3.10+ with GTK4/libadwaita, FFmpeg, Chromecast (`catt`)
and DLNA. Native setup is under `setup/`; ordinary tests do not import GTK.

## GTK window: seven smaller modules

The main GTK application is assembled by `src/cast_control.py`, which has
`MainWindow.__init__`, `CastControlApp` and `main`. The window inherits:

| Concern | Module |
| --- | --- |
| Cards, menus, queue widgets, console, theme, UI controls | `src/cast_ui.py` (`UiMixin`) |
| Files, queue, device discovery, output selection | `src/cast_queue.py` (`QueueMixin`) |
| Casting, seeking, transport, sleep/window state | `src/cast_session.py` (`SessionMixin`) |
| Audio, subtitles, volume, local preview, meters | `src/cast_av.py` (`AvMixin`) |
| Closing, cleanup, menu actions, screenshots | `src/cast_lifecycle.py` (`LifecycleMixin`) |
| Shared GTK widgets, config, constants | `src/cast_widgets.py` |

For source-level GUI tests use `tests/gui_source.py`:
`combined_source()` for substring assertions and
`main_window_methods()` for AST method lookup. **Do not** rebuild a giant
single GUI file or import GTK during ordinary tests.

## Discovered receiver identity

The selected Cast receiver has a human-friendly `device` and (when mDNS
provides one) a persisted `device_uuid`. An idle discovery scan may recover
a renamed receiver **only** if both its UUID and new display name are unique.
Never migrate selection while a cast, remote URL, startup or transport command
is active. Manual IP/DLNA selections intentionally clear the Cast UUID. Do
not assume a display name alone proves ownership; issue #15 (SC-008)
still tracks duplicate-name, stale-IP and real-device qualification.

## HLS stall watchdog (P0 SC-010)

`stream_watchdog.StreamWatchdog` is a pure, monotonic-clock state machine.
The GUI tick supplies cached FFmpeg and receiver progress; the
watchdog performs no disk, network, GTK or process work.
A sustained encoder stall (24 s) or a receiver that stops advancing while
FFmpeg continues (36 s) can trigger **one** automatic HLS restart at the
source-file playback position. It requires the receiver to report the **exact
saved stream URL and optional title**, and refuses paused, offline, busy,
unknown/foreign or completed playback. The one-restart budget survives
FFmpeg generation changes; a subsequent failure displays an error instead of
looping forever. A confirmed receiver IDLE/end is handled by the existing
completion path and never converted into a restart.

The asynchronous restart goes through `SessionMixin._restart_at`. Do not
schedule extra background polling or launch GTK to test; deterministic unit
and UI-wiring checks live in `tests/test_stream_watchdog.py`. Real-device
buffering and first-frame behavior still require qualification under
[GitHub issue #17](https://github.com/gmanldn/smoothcast/issues/17).

## Direct Cast acceptance and safe HLS fallback

`src/direct_probe.py` classifies receiver status after the `catt`
direct-cast command returns: verified PLAYING/PAUSED with matching title is
accepted; three consecutive explicit IDLE reports mean the decoder failed
and a background HLS handoff may be attempted at the **same source position,
audio setting and sidecar subtitles**. An unavailable/ambiguous status
retains the direct stream rather than guessing it failed. A known foreign
active title aborts automatic fallback without sending a remote Stop.

Polling runs in the existing cast-start worker, never GTK. The probe is
bounded (three calls, two 0.6 s pauses); `tests/test_direct_failover_probe.py`
covers the classifier and the worker's direct-to-HLS branch with fakes. Real
device decoder/subtitle negotiation remains P0 issue #18.

## Subtitle selection on encoder restarts (P0 SC-015)

`SessionMixin._restart_at` preserves the exact saved external subtitle
file, its burn-in mode, or the selected embedded *stream index*. It first
probes the current source and calls `subtitle_restart.validate_restart`
**inside the existing background worker and before stopping the old stream**.
A vanished/unsupported sidecar or a missing/bitmap replacement for an
explicit embedded text track is a visible error; do not silently choose the
new preferred/forced track or restart without captions. ASS/SSA files must
always burn in, even if an old persisted state mistakenly says otherwise.
`tests/test_subtitle_restart.py` executes the real handler with fakes and
checks no Cast command is sent when selection validation fails.

Subtitle delay, forced-track overrides and real-device transfers remain open
in [issue #22](https://github.com/gmanldn/smoothcast/issues/22).

## HLS generation identity (P1 SC-062)

Every `streamer.Session.start_transcode` generates a random 128-bit stream ID
(`secrets.token_hex(16)`). The playlist is `movie-<32 hex>.m3u8` with matching
`segment-<same ID>-00000.ts` files. **Both paths must change** on every
seek/restart or film switch: an ID in a URL query would let a delayed old
request load replacement bytes through the same file.

`src/server.py` (binds `0.0.0.0:8767`) serves only exact generated basenames,
the health endpoint and read-only legacy names (`movie.m3u8`, `segment-N.ts`)
for already saved sessions; never directories, logs, subtitle staging or
configuration. A stale request gets 404, not another film's frames. Persist the
exact URL in `SessionState.stream_url`: watchdog, receiver ownership and
recovery compare the full URL. Finalised single-segment recovery must verify
every playlist segment belongs to its saved generation.

`tests/test_hls_generation_identity.py` uses loopback servers and mock
encoders/TV; do not launch GTK or command a receiver.

## Cast diagnostics and workers

`network_route_ui.start` runs opt-in Cast checks off-thread and rejects late
results ([setup](../../setup/README.md)). `Async.run` uses bounded per-domain
queues with GLib callbacks ([worker domains](../ASYNC_WORKERS.md)).

## Other subsystems

- Media pipeline: `src/streamer.py`, `src/preflight.py`,
  `src/subtitle_encoding.py`, `src/audio_monitor.py`.
- Receivers: `src/castctl.py` (runs the `catt` CLI as a subprocess per
  command), `src/cast_targets.py`, `src/dlna.py`, `src/url_control.py`.
- Preview and state: `src/local_playback.py`, `src/playback_state.py`,
  `src/position_tracker.py`, `src/responsive_layout.py`,
  `src/watch_history.py`.
- Workers, diagnostics, recovery: `src/async_jobs.py`,
  `src/network_routes.py`, `src/diagnostics.py`, `src/startup_cleanup.py`,
  `src/update_control.py`, `src/library_index.py`, `src/benchmark.py`.
- Headless entry `src/cli.py`: `--version`, `--diagnostics`,
  `--network-check`, `--library-index`. Only the seven GUI modules above
  import `gi`; keep all other modules GTK-free.
- Launch and desktop: `setup/`, `scripts/install_desktop.py`,
  `src/version.py`. Tests and CI: `tests/`, `.github/workflows/verify.yml`.
- Roadmap: epic [#201](https://github.com/gmanldn/smoothcast/issues/201).

## Asynchronous receiver transport safety

`SessionMixin.toggle_play` and `SessionMixin.seek_to` serialize direct
Google Cast and DLNA transport commands with the window's `busy` guard.
Every UI action, including keyboard shortcuts and seekbar signals, must obey
that guard *before* changing optimistic UI state. Worker callbacks only
update controls for the unchanged session and selected device and must
release the guard on both success and failure. On failure, poll the receiver
to resynchronise the displayed state; never infer success from an issued
command alone. Stop and cast transitions are separate ownership paths.

This is a slice of P0 SC-009 (issue #16); cancellation, retry policy and
physical receiver acceptance remain open. Tests:
`tests/test_transport_serialization.py`.

Follow runtime state ownership through the whole cast/cleanup lifecycle.
Historical edge cases: [archive](../AGENT_REFERENCE.md).
