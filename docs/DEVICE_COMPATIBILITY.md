# Device compatibility

Results reported by users and maintainers for specific receivers. Each row is
one receiver on one SmoothCast version. **A row is evidence from a real device,
not a guarantee.** CI never proves receiver behaviour (see
[testing](agents/testing.md)).

Submit a result with the [Device compatibility report](https://github.com/gmanldn/smoothcast/issues/new?template=device-report.yml) form.
Only publish results that were observed on the named device; automated fakes
and runner checks do not qualify receivers.

Legend: ✅ passed · ❌ failed · ➖ not tested.

| Receiver (make / model) | Protocol | Firmware | SmoothCast | Computer OS | Date / tester | Direct play | Transcode | Pause / seek | Subtitles | Volume | Other scenarios / notes | Report |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| *No verified receivers yet* | | | | | | | | | | | | |

Records follow `docs/device-record.schema.json` and are stored in
`data/devices/*.yaml`; regenerate this page with
`python3 scripts/generate_compatibility.py`. Each record is dated and names
the tester, device, firmware (when known), SmoothCast version and OS.

Support tiers are assigned only from evidence: **Unverified** (no report),
**Compatible** (community report), **Qualified** (maintainer verified),
or **Known issues** (a reproducible failure is recorded). This table does
not imply broader model-family support.

Related: native DLNA hardware qualification is tracked in
[#8](https://github.com/gmanldn/smoothcast/issues/8).
