# Platform status

Status recorded **21 November 2026** for SmoothCast commit
[`abffb94`](https://github.com/gmanldn/smoothcast/commit/abffb9494b4b655da5a3371e579eaa4a58de8826).
Passing CI verifies the listed automated checks; it does not qualify native GUI
playback or receiver interoperability.

| Platform | Automated evidence | Native desktop and real-cast status |
| --- | --- | --- |
| Linux: Debian 13, x86_64 workbench; Ubuntu 24.04 CI | Verify SmoothCast [run 44878517277](https://github.com/gmanldn/smoothcast/actions/runs/44878517277) passed the Linux portable regression, media-integration, setup-contract, and installed-artifact jobs. | **Unverified.** No native GUI or receiver test was run for this qualification matrix. |
| macOS 15 runner | Verify SmoothCast [run 44878517277](https://github.com/gmanldn/smoothcast/actions/runs/44878517277) passed the portable regression, setup-contract, and installed-artifact jobs on `macos-15`. | **Unverified.** CI does not launch the native app or cast to a real receiver. |
| Windows 2025 runner | Verify SmoothCast [run 44878517277](https://github.com/gmanldn/smoothcast/actions/runs/44878517277) passed the portable regression, setup-contract, and installed-artifact jobs on `windows-2025`. | **Unverified.** CI does not launch the native app or cast to a real receiver. |

## Remaining qualification work

Issue [#209](https://github.com/gmanldn/smoothcast/issues/209) remains open.
Its native checks need macOS and Windows desktop sessions plus a real
Chromecast, and Linux GUI/device checks need an explicitly scoped receiver
session. The current host is Debian Linux; those native sessions and a receiver
were not available for this run. Portable CI must not be reported as GUI,
network-discovery, or Chromecast playback evidence.

The matrix above records runner-level evidence only. Add dated rows with the
OS version, architecture, SmoothCast commit, named receiver and per-scenario
results after a native qualification run. Keep receiver protocol compatibility
in [Device compatibility](DEVICE_COMPATIBILITY.md).

## Hardware encoder port evidence (#703)

Backends live in `src/hw_port.py`; `select()` degrades to the next ranked
backend and records the skip reason. Evidence is unit-level (injected probes,
`tests/test_hw_port.py`); native-device results are UNVERIFIED until a dated
row is added.

| Backend | Platforms gated in code | Probe | Unit evidence | Native device |
|---|---|---|---|---|
| VAAPI | Linux only | probed `/dev/dri/renderD*` nodes | yes | UNVERIFIED |
| NVENC | any (ffmpeg must list `h264_nvenc`) | `ffmpeg -encoders` | yes | UNVERIFIED |
| QSV | not macOS | `ffmpeg -encoders` | yes | UNVERIFIED |
| VideoToolbox | macOS only | `ffmpeg -encoders` | yes | UNVERIFIED |
| Software | all | none (final fallback) | yes | n/a |

`src/streamer.py` still uses its fixed VAAPI path; moving it onto `select()`
is the open slice.
