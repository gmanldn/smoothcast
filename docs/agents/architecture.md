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

`SessionMixin.toggle_play` and `SessionMixin.seek_to` serialize direct
Google Cast and DLNA transport commands with the window's `busy` guard.
Every UI action, including keyboard shortcuts and seekbar signals, must obey
that guard *before* changing optimistic UI state. Worker callbacks only
update controls for the unchanged session and selected device and must
release the guard on both success and failure. On failure, poll the receiver
to resynchronise the displayed state; never infer success from an issued
command alone. Stop and cast transitions are separate ownership paths.

This is the bounded transport-safety slice of P0 SC-009 (GitHub issue #16);
cancellation, retry policy and full physical receiver acceptance remain
open there. The GTK-free tests live in `tests/test_transport_serialization.py`.

Search symbols and affected callers before opening large files; follow runtime
state ownership through the whole cast/cleanup lifecycle. For historical
edge-case notes see [archived instructions](../AGENT_REFERENCE.md).
