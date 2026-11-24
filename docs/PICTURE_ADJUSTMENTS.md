# Picture adjustments — SC-103 / issue #112

SmoothCast offers brightness, contrast, saturation and hue controls under
**Preferences → Playback → Colour adjustments**. All controls default to
neutral, so previously encoded videos are unchanged. **Reset picture**
removes the selected film's saved preset; with no film selected it
restores the global defaults.

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

## Per-film presets (24 Nov 2026)

Changing a control while a film is loaded stores the effective four-value
preset in `picture_by_file`, keyed by the film path. Films without a saved
preset use the global controls as their fallback, so existing behaviour is
unchanged. Reset removes only the selected film's preset and leaves other
films and the global defaults intact.

The resolved preset is used consistently for direct-play eligibility,
transcode and restart filters, and local preview frames. The config loader
bounds the map, validates every stored value and drops malformed entries.
The GTK controls show the selected film's resolved values and write back to
its preset.

Tests: `python3 -m pytest -q tests/test_picture_adjustments.py
tests/test_picture_adjustments_preview.py
tests/test_preferences_behaviour.py`.

## Verification boundary

The software acceptance for #112 is complete: validated filters, neutral
defaults, reset, local preview parity, per-film persistence and focused
headless tests. A GTK/receiver visual colour comparison and DLNA lifecycle
qualification still need a physical device; those pending checks are tracked
in #208 and are not a prerequisite for closing the software ticket.
