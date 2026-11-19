# Release qualification dashboard

[GitHub Issues](ISSUES.md) remain the only backlog. The qualification dashboard
is **evidence per release and commit**, not another task list. It does not run
or claim a GUI/device test; a missing entry means **PENDING**, never passing.

Promotion to `main` is a release merge from `develop`; `main` is protected, so
release commits never land there directly.

## Use

From the repository root, with no GTK, FFmpeg or receiver required:

```sh
python3 scripts/ci/release_qualification.py
python3 scripts/ci/release_qualification.py --strict
python3 scripts/ci/release_qualification.py --output /tmp/smoothcast-qualification.md
```

The default release comes from `src/version.py` (read as source without execution).
The dashboard intentionally begins **NOT QUALIFIED** until somebody records
traceable evidence. To start collecting checks for a release at a frozen Git
commit:

```sh
python3 scripts/ci/release_qualification.py --init \
  --release 1.2.3 --sha "$(git rev-parse HEAD)"
```

Replace `1.2.3` with the release being qualified. This **refuses to overwrite**
an existing entry. The `docs/release_qualification.json` file is versioned
in Git. It starts empty to avoid inventing historical qualification results.
Add individual check objects under `releases["1.2.3"]["checks"]`:

```json
{
  "portable-python-310": {
    "status": "pass",
    "evidence": "https://github.com/gmanldn/smoothcast/actions/runs/123",
    "checked_at": "2026-11-19T10:00:00Z",
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "cast-chromecast": {
    "status": "fail",
    "evidence": "https://github.com/gmanldn/smoothcast/issues/42",
    "checked_at": "2026-11-19T10:00:00Z",
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "device_model": "Chromecast 3",
    "notes": "Start succeeded; seeking failed on the receiver"
  }
}
```

The 40-character example SHA must be replaced by the **actual exact tested
commit**, matching the release entry; a mismatch is reported **STALE**, not
passed. `pass` or `fail` requires dated HTTPS evidence; physical-device checks
also require a model and notes. Optional unsupported hardware may be set to
`{"status":"unsupported","notes":"reason"}`; required checks cannot be
marked unsupported. Unknown keys or invalid evidence cause an error rather than
an optimistically green dashboard.

To record a known issue separately from check status:

```json
{"summary": "Seek fails on model X", "status": "open", "issue": "https://github.com/gmanldn/smoothcast/issues/8"}
```

Put this in the release's `known_failures` array; change `status` to
`resolved` only with real closure evidence in the linked issue.

## Gates and coverage

Mandatory: Python 3.10/3.13 portable CI, FFmpeg media integration, MKV and SRT
samples, Linux/macOS/Windows setup contracts and installed wheels, isolated
GTK smoke, and a real Chromecast play/seek/stop session. The report also tracks
LG, Samsung, Sony DLNA; Apple TV AirPlay; and Roku separately as optional
platform coverage, not implicitly supported protocols. An unresolved known
failure or any reported check failure blocks qualification; required pending
or stale checks prevent qualification. **QUALIFIED (required gates)** does
not imply optional device coverage.

[GitHub Verify workflow](https://github.com/gmanldn/smoothcast/actions/workflows/verify.yml)
provides portable, codec, setup and wheel evidence from specific commit runs;
it does **not** run GTK or physical receiver smoke. Use
`python3 scripts/test_gui_isolated.py` only in its isolated Xvfb environment,
never against the user's current desktop. For device results, test on
actual consented equipment; do not infer a pass from a fake/mock.

## Tests

`python3 -m pytest -q tests/test_release_qualification.py` verifies missing,
stale, erroneous, unsupported, failing and fully evidenced states. Normal
CI's `python3 -m pytest -q tests` discovers these regressions without opening
GTK or touching the LAN. A release cannot be signed off by this dashboard
until external evidence is entered.
