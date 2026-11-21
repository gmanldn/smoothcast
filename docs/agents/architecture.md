# SmoothCast architecture — open the relevant module

SmoothCast is Python 3.10+ with GTK4/libadwaita, FFmpeg, Chromecast (`catt`)
and DLNA. Ordinary tests do not import GTK.

<!-- invariant: INV-009 -->

<!-- invariant: INV-009 -->

## GTK window: seven smaller modules

<!-- invariant: INV-011 -->

<!-- invariant: INV-011 -->

Main GTK entry point: `src/cast_control.py`; `MainWindow` inherits:

| Concern | Module |
| --- | --- |
| Cards, menus, queue widgets, console, theme, UI controls | `src/cast_ui.py` (`UiMixin`) |
| Files, queue, device discovery, output selection | `src/cast_queue.py` (`QueueMixin`) |
| Casting, seeking, transport, sleep/window state | `src/cast_session.py` (`SessionMixin`) |
| Audio, subtitles, volume, local preview, meters | `src/cast_av.py` (`AvMixin`); delay: `src/cast_subtitles.py` |
| Closing, cleanup, menu actions, screenshots | `src/cast_lifecycle.py` (`LifecycleMixin`) |
| Shared GTK widgets, config, constants | `src/cast_widgets.py` |
| LAN dashboard, shared room, dispatch | `src/cast_portal.py`, `src/cast_portal_queue.py` |
| Command fencing and replay | `src/portal_commands.py` |

For GUI tests use `tests/gui_source.py`:
`combined_source()` for substring assertions and
`main_window_methods()` for AST lookup. **Do not** rebuild a giant GUI file
or import GTK in ordinary tests.

## Discovered receiver identity

<!-- invariant: INV-001 -->

<!-- invariant: INV-001 -->

The selected Cast receiver has a friendly `device` and optional persisted
`device_uuid`. An idle scan may recover a renamed receiver only when its UUID
and new name are unique. Manual IP/DLNA selections clear that UUID. Display
names alone do not prove ownership; #15 tracks mDNS reconciliation and device
qualification. Host lookup rejects duplicate/missing current records and
failed scans, so it cannot reuse an old address.

## HLS stall watchdog (P0 SC-010)

<!-- invariant: INV-002 -->

<!-- invariant: INV-002 -->

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

<!-- invariant: INV-003 -->

<!-- invariant: INV-003 -->

`src/direct_probe.py` classifies receiver status after the `catt`
direct-cast command returns: verified PLAYING/PAUSED with matching title is
accepted; three consecutive explicit IDLE reports mean the decoder failed
and a background HLS handoff may be attempted at the **same source position,
audio setting and sidecar subtitles**. An unavailable/ambiguous status
retains the direct stream rather than guessing it failed. A known foreign
active title aborts automatic fallback without sending a remote Stop.

All polling runs in the existing cast-start worker, not GTK or routine test
runs. The probe is deliberately bounded (three calls, two 0.6 s pauses);
`tests/test_direct_failover_probe.py` exercises both the pure classifier
and the actual cast worker's direct-to-HLS branch with fakes. Real device
decoder/subtitle negotiation remains P0 issue #18.

## Subtitle selection on encoder restarts (P0 SC-015)

<!-- invariant: INV-004 -->

<!-- invariant: INV-004 -->

`SessionMixin._restart_at` preserves the saved external subtitle
file, its burn-in mode, or the selected embedded *stream index*. It first
probes the current source and calls `subtitle_restart.validate_restart`
**inside the existing background worker and before stopping the old stream**.
A forced disposition remains attached to that exact source stream on reprobe.
A vanished/unsupported sidecar or a missing/unsupported replacement for an
explicit embedded track is a visible error; do not silently choose the
preferred/forced track or restart without captions. ASS/SSA files must
always burn in, even if an old persisted state mistakenly says otherwise.
Bitmap overlay is software-only.
`tests/test_subtitle_restart.py` executes the real handler with fakes and
checks no Cast command is sent when selection validation fails.

Subtitle delay lives in `src/cast_subtitles.py`; device timing and renderer
transfers stay under [issue #22](https://github.com/gmanldn/smoothcast/issues/22).

## HLS generation identity (P1 SC-062)

<!-- invariant: INV-005, INV-006 -->

<!-- invariant: INV-005, INV-006 -->

Every new `streamer.Session.start_transcode` generates a cryptographically
random 128-bit stream ID. The playlist is
`movie-<32 lowercase hex>.m3u8`, with matching
`segment-<same ID>-00000.ts` files. **Both paths must change** on every
seek/restart or film switch: merely putting an ID in a URL query would allow
a delayed old request to load replacement bytes through the same file.

The LAN HTTP server permits only exact generated playlist/segment basenames
(and read-only legacy names for already saved sessions). It never exposes
directories, logs, subtitle staging, configuration or arbitrary files. New
starts remove stale HLS assets; a stale receiver request returns 404 instead
of frames from a different film or seek point. Persist the exact generation
URL in `SessionState.stream_url`: watchdog, receiver ownership and recovery
compare that full URL. Finalised single-segment HLS recovery must verify
every playlist segment belongs to its saved generation.

`tests/test_hls_generation_identity.py` checks real loopback GET/HEAD,
cross-generation stale requests, narrow allowlists, encoder arguments and
finalised recovery. All tests use mock encoders/TV and ephemeral local
servers; do not launch GTK or send commands to a receiver.

## Cast diagnostics and workers

<!-- invariant: INV-007, INV-010 -->

<!-- invariant: INV-007, INV-010 -->

`network_route_ui.start` runs opt-in Cast checks off-thread; late
results are rejected. See [setup](../../setup/README.md).
`Async.run` now uses bounded, separate I/O queues with GLib callback
delivery. See [worker domains](../ASYNC_WORKERS.md).

## Other subsystems

- Media pipeline: `src/streamer.py`, `src/preflight.py`,
  `src/subtitle_encoding.py`, `src/audio_monitor.py`.
- Preview and responsiveness: `src/local_playback.py`,
  `src/responsive_layout.py`, `src/position_tracker.py`.
- Receiver protocols: `src/castctl.py` and `src/dlna.py`.
- Reliability and diagnostics: `src/startup_cleanup.py`,
  `src/update_control.py`, `src/diagnostics.py`.
- Launch and desktop: `setup/`, `scripts/install_desktop.py`,
  `src/version.py`.
- Tests and CI: `tests/`, `.github/workflows/verify.yml`.

## Asynchronous receiver transport safety

<!-- invariant: INV-008 -->

<!-- invariant: INV-008 -->

`SessionMixin.toggle_play` and `SessionMixin.seek_to` serialize direct
Google Cast and DLNA transport commands with the window's `busy` guard.
Every UI action, including shortcuts and seekbar signals, must obey that guard
before changing optimistic state. Callbacks update controls only for the same
session/device; release the guard on success or failure. On failure, poll the
receiver; never infer success from an issued command.
Stop UI trusts receiver acknowledgement; local cleanup alone is not proof that
TV playback stopped. DLNA volume/mute need its optional RenderingControl service.

This is the bounded transport-safety slice of P0 SC-009 (GitHub issue #16);
cancellation, retry policy and full physical receiver acceptance remain
open there. The GTK-free tests live in `tests/test_transport_serialization.py`.

Search symbols and affected callers before opening large files; follow runtime
state ownership through the whole cast/cleanup lifecycle. For historical
edge-case notes see [archived instructions](../AGENT_REFERENCE.md).
