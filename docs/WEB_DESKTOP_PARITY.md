# Web ⇄ desktop parity matrix

Owner directive (#635): the browser room should be as fully featured as the
desktop, subject to host-local security boundaries. This table is the ratchet —
`tests/test_web_desktop_parity.py` fails when a listed desktop marker or browser
control disappears, so parity claims cannot silently drift. Update the row in the
same commit that changes a surface.

State values: `present` (browser control exists), `partial` (some of the desktop
behaviour is exposed), `gap` (not exposed yet). Every `gap` or `partial` row must
name the tracking issue.

| Area | Desktop source | Browser surface | State |
| --- | --- | --- | --- |
| Tracks and subtitles | `src/cast_subtitles.py` | none | gap (#635) |
| Timing and seek | `src/cast_ui.py::SeekBar(` | `#seek` `#progress` `#elapsed` | present |
| Picture and video adjustments | `src/preferences_picture_ui.py` | none | gap (#635) |
| Audio tracks, delay and volume | `src/cast_control.py::_adjust_audio_delay` | `#volume` | partial (#635) |
| Chapters | `src/cast_ui.py::_build_chapters_menu` | `#chapterJump` | present |
| Queue / Up Next | `src/cast_queue.py::queue_list` | `#queuePanel` `#queue` | present |
| Local preview | `src/cast_ui.py::PreviewScreen()` | none | gap (#635) |
| Host settings and display name | `src/preferences_ui.py` | `#advancedPanel` | partial (#635) |
| Find and link acquisition | `src/link_acquisition.py` | `#findPanel` | present |
| Room activity and mesh health | `src/cast_control.py::_reload_services` | `#meshPanel` `#localLivePanel` | present |

## Remaining work to reach parity

- Subtitle and audio-track selection, subtitle delay and the picture adjustment
  panel have no browser control yet; they stay host-side until a fenced envelope
  exists for them (#635).
- Audio delay/sync is host-only beyond browser volume (#635).
- Local preview stays desktop-only: the browser must not mirror the host screen.
- Host-only surfaces (House PIN, library folders, mesh credentials, update
  channel) must never be exposed to the browser; the browser keeps its
  host-local security boundary.
