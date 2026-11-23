# Sparse cached scrub previews (#40 / SC-031)

Seekbar hovering groups source times into ten-second slots. A bounded
96-image JPEG LRU reuses a slot's decoded image immediately, avoiding a
fresh FFmpeg decoder for every mouse movement. Cache identity includes
the selected film, stream index and preview generation; old film frames
cannot be presented after another film is selected. The existing
180ms debounce and single active background decoding job remain.

Explicit seeks, local playhead updates and frame stepping bypass slot
quantisation and remain source-time-accurate. Subtitle cue lookup still
uses the user's exact hovered source timestamp.

Regression: pytest -q tests/test_sparse_thumbnail_cache.py.
Full issue #40 is still OPEN: a visible row/strip of adjacent thumbnails
and isolated GUI UX verification remain to implement. Hardware checks
are tracked through #208.
