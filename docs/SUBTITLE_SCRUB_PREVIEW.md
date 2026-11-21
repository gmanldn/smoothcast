# Subtitle cue scrub preview (#37 / SC-028)

Hover the seekbar while previewing a local film to see the selected or automatically matched sidecar caption at that **source-film timestamp**. Supports SRT (including UTF-16 and Windows-1252), WebVTT, ASS and SSA; HTML/ASS styling is stripped in the preview only. The existing subtitle selection and forced/full embedded-track selectors are unchanged. No TV or receiver commands are sent.

Cue files are validated as ordinary local non-symlink files, capped at 16 MiB, and parsed once in an asynchronous media worker. The current source and file identity are checked before displaying results; rapid mouse movements reuse the same worker and the in-memory timestamp index. Moving off the seekbar restores the ordinary subtitle status. Preview is informational and does not change caption timing, subtitle choice or playback position.

GTK-free regression: `pytest -q tests/test_subtitle_preview.py`. The implementation currently does **not** extract and show embedded MKV subtitle text as a timed cue; that requires a bounded, cancellable per-track extraction worker with its own lifecycle and tests before #37 is fully complete. Physical receiver overlay timing remains tracked in #208.
