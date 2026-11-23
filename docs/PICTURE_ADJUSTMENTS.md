# Picture adjustments — SC-103 / issue #112

SmoothCast offers brightness, contrast, saturation and hue controls under
**Preferences → Playback → Colour adjustments**. All controls default to
neutral, so previously encoded videos are unchanged. **Reset picture**
restores the neutral values.

| Setting | Neutral | Accepted values |
| --- | ---: | ---: |
| Brightness | 0 | -0.5 to 0.5 |
| Contrast | 1 | 0.5 to 1.5 |
| Saturation | 1 | 0 to 2 |
| Hue, degrees | 0 | -180 to 180 |

The GTK-free `picture_adjustments` module validates untrusted preferences
(type, finite numeric value, bounds) and creates FFmpeg filter arguments,
never shell commands. Invalid saved values become neutral. The encoder
applies adjustments before burned-in subtitles, preserving caption colours.
A non-neutral setting disables direct-play eligibility and forces the
software encoding path if the hardware pipeline cannot implement the
adjustment. It is passed through Cast HLS restarts. Only the next cast or
transcode restart is affected; a currently playing receiver is not
reconfigured automatically.

Tests: `python3 -m pytest -q tests/test_picture_adjustments.py`.

## Local preview parity (23 Nov 2026)

Local pre-cast JPEG frames now use the same validated `eq`/`hue`
filter builder as the cast transcode path, before the preview scaling
filter. Asynchronous frames capture a snapshot of the colour settings;
changing a control or resetting the picture invalidates the old
preview generation and requests a fresh frame without touching an
owned receiver. Both sparse/hover previews and exact-position frames
are covered by a headless regression.

This is a **preview of the chosen filter values**, not a claim of
display-calibrated colour: colour management, HDR tone mapping, decoder
differences and the final receiver display can still differ.

Tests: `python3 -m pytest -q tests/test_picture_adjustments.py tests/test_picture_adjustments_preview.py`.

## Remaining acceptance — do not close #112 yet

The controls remain **global preferences**, not per-film or
per-receiver presets. DLNA conversion, dynamic direct-to-HLS transitions,
real GTK previews on Linux/macOS/Windows and a physical-device colour
comparison still need qualification. Do not mark #112 complete until
preset-scoped persistence, lifecycle and device checks are verified.
