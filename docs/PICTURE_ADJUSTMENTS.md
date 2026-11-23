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

## Remaining acceptance — do not close #112 yet

The current controls are **global preferences**, not per-film or
per-receiver presets. Local video preview has not yet been adjusted to
represent the encoded output; existing screenshot/thumbnail behaviour
must not be advertised as accurate colour preview. DLNA conversion
and dynamic direct-to-HLS transitions require separate validation.
Finish preview, preset-scoped persistence, lifecycle and device tests
before marking #112 complete.
