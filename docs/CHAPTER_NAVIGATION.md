# Chapter navigation (#39 / SC-030)

FFprobe now reads chapters in the existing background media probe. For the
currently previewed or owned Cast/DLNA film, the Chapters menu displays
chapter titles and source-film start/end times. Selecting a chapter delegates
to the existing seek_to path (including source-time HLS restart), with an
ownership check before seeking and no separate clock.

Chapter timing prefers rational FFprobe ticks/time_base; entries with
nonfinite, invalid, overlapping or out-of-bounds timestamps are skipped.
Parsing is capped at 128 visible chapters. Changes of film refresh the menu
and stale actions refuse to seek foreign or old media.

Run: pytest -q tests/test_chapter_navigation.py. This is GTK-free and never
opens the desktop or controls a receiver. Physical device qualification
continues under #208.

Unfinished: FFprobe does not expose complete Matroska EditionEntry graphs.
Ordered/linked editions may have non-linear timelines; their switching and
segment mapping are not implemented. Do not close #39 until edition
selection, its playback semantics and focused tests are complete.
