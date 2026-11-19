# Device compatibility

Results reported by users and maintainers for specific receivers. Each row is
one receiver on one SmoothCast version. **A row is evidence from a real device,
not a guarantee.** CI never proves receiver behaviour (see
[testing](agents/testing.md)); until rows appear below, no receiver is verified.

Submit a result with the
[Device compatibility report](https://github.com/gmanldn/smoothcast/issues/new?template=device-report.yml)
form, attaching the bundle from `smoothcast --diagnostics` (it includes the
receiver's protocol and model, with addresses and paths redacted).

Legend: ✅ worked · ❌ failed · ➖ not tested.

| Receiver (make / model) | Protocol | Firmware | SmoothCast | Computer OS | Direct play | Transcode | Pause / seek | Subtitles | Volume | Report |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *No verified receivers yet* | | | | | | | | | | |

## Adding a row

1. Confirm the report's version, protocol and results are specific and its
   diagnostics bundle shows the same receiver model.
2. Add one row per receiver and SmoothCast version, linking the issue. Never
   merge two receivers or generalise ("all Chromecasts work").
3. A failing result stays in the table: it is how regressions are found.

Related: native DLNA hardware qualification is tracked in
[#8](https://github.com/gmanldn/smoothcast/issues/8).
