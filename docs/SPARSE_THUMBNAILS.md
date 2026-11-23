# Sparse cached scrub previews (#40 / SC-031)

Seekbar hovering groups source times into ten-second slots. A bounded
96-image JPEG LRU reuses a slot's decoded image immediately, avoiding a
fresh FFmpeg decoder for every mouse movement. Cache identity includes
the selected film, stream index and preview generation; old film frames
cannot be presented after another film is selected. The existing
180ms debounce and single active background decoding job remain.

While scrubbing, the desktop shows up to five cached neighboring frames in a
strip beneath the seekbar. The strip is populated only from images already in
the bounded LRU, so it never schedules extra decoders; it fills progressively
as the user scrubs across new slots. Each tile is labelled with its source
timestamp and selecting one seeks to that exact timestamp. It remains visible
after the pointer leaves the seekbar so the tiles can be selected, and resets
when the selected film is cleared.

Explicit seeks, local playhead updates and frame stepping bypass slot
quantisation and remain source-time-accurate. Subtitle cue lookup still
uses the user's exact hovered source timestamp.

Regression: pytest -q tests/test_sparse_thumbnail_cache.py.
The GTK strip itself is not launched in routine tests; isolated GUI UX
verification remains a separate acceptance check. Hardware checks are tracked
through #208.
