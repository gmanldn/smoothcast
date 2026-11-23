# Subtitle cue scrub preview (#37 / SC-028)

Hover the seekbar while previewing a local film to see the selected or automatically matched sidecar caption, or the selected embedded text-track caption, at that **source-film timestamp**. Supports SRT (including UTF-16 and Windows-1252), WebVTT, ASS and SSA; HTML/ASS styling is stripped in the preview only. Bitmap subtitle tracks have no text to preview. The existing subtitle selection and forced/full embedded-track selectors are unchanged. No TV or receiver commands are sent.

Cue files are validated as ordinary local non-symlink files, capped at 16 MiB, and parsed once in an asynchronous media worker. Embedded text is extracted from only the selected stream by FFmpeg, with a 16 MiB output cap and 15-second timeout. The current source, file identity, track selection and generation are checked before displaying results; rapid mouse movements reuse the same worker and the in-memory timestamp index. Moving off the seekbar restores the ordinary subtitle status. Preview is informational and does not change caption timing, subtitle choice or playback position.

GTK-free regressions: `pytest -q tests/test_subtitle_preview.py`. The tests exercise sidecar parsing, bounded embedded-track extraction, source ownership and scrub hover wiring. Physical receiver overlay timing remains tracked in #208.
