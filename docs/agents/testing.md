# Agent testing and safety — never focus the user's desktop

**Non-negotiable:** routine tests must not launch SmoothCast, steal focus, alter
GNOME dock pins, discover/control the user's TV, or touch real media. Never use
`gtk-launch`, `./smoothcast` (except `--version`), plain
`python3 src/cast_control.py`, or bare `--self-test` in a test loop.
Do not use the user's live X11/Wayland display or desktop DBus (D-Bus).

Headless portable verification from repo root:

```sh
python3 -m pytest -q tests
python3 -m compileall -q src scripts setup tests
```

Run targeted `python3 -m pytest -q tests/test_affected.py` during iteration,
then the full suite when appropriate. The test harness strips desktop
display/session handles at collection; CI sets `SMOOTHCAST_TEST_CONTEXT=1`.
Never remove these guards or run tests repeatedly to check whether the GUI
raises a window. `tests/gui_source.py` is for source/AST UI assertions
without importing GTK.

**CI gates (#250-#255, #260, #262):** `ruff check src scripts setup tests sc.py
setup.py` fails on new violations; the 3.13 job gates `--cov-fail-under=38`
(raise, never lower). **Types (#251):** `mypy` gates only `[tool.mypy] files`;
widen by making `mypy src/<module>.py` clean, then listing it. `pip-audit`,
CodeQL, Dependabot and `.pre-commit-config.yaml` back this; `catt` is bounded
`>=0.12,<0.14` in `pyproject.toml` and `setup/bootstrap.py` (a test keeps them
equal). **Fuzzing:** `tests/test_fuzz_parsers.py` (Hypothesis, seeded) holds
parsers to their documented error; add each find as a regression.

**Action integrity (#256):** all remote `uses:` entries in
`.github/workflows/*.yml` must pin the immutable 40-character upstream commit
SHA and retain the upstream major version as a comment (`# v4`). This avoids
trusting a movable tag while remaining compatible with weekly Dependabot
GitHub Actions updates. `tests/test_actions_sha_pinning.py` scans all present
and newly added workflows; update pinned refs only after reviewing their
upstream release and the exact SHA. Keep CodeQL init/analyze on the same commit.

**Fake receivers (#278):** `tests/fake_receivers.py` tests playback without a
TV and mocks nothing in `dlna`/`castctl`: `FakeDlnaRenderer` (real HTTP/SOAP on
loopback, inside `allow_loopback()`) and `FakeCast` (a stand-in `catt`, POSIX).
Time moves only on `advance(seconds)`; script `fail`, `drop`/`go_offline`,
`delay`; read `calls`. Examples: `tests/test_fake_receivers.py`. They do not
replace device tests.

**Minimum FFmpeg (#242):** `ffmpeg_compat.require_supported_ffmpeg` runs a
bounded, GTK-free `ffmpeg -version` query before a receiver is replaced;
SmoothCast requires FFmpeg 5.0+ for `-readrate` and
`scale:force_divisible_by`. New-cast and restart workers check before
stopping previous streams; transcode paths recheck before launching an encoder.
`tests/test_ffmpeg_version_guard.py` mocks all subprocess calls and verifies
rejecting unknown/broken/older builds without sending Cast commands.

**macOS/Windows (#258):** `portable-tests-native` runs this suite there
(it gates, incl. release promotion). A test that cannot pass is listed by exact id, with a reason, in
`tests/platform_gaps.py` and skipped on that OS only; fix the cause and delete
the entry. "PRODUCT BUG" marks a SmoothCast defect, not a test quirk.

**CI FFmpeg integration:** `.github/workflows/verify.yml` runs actual
subtitle/preflight/DLNA media tests after ensuring both `ffmpeg` and
`ffprobe` are available. `scripts/ci/ensure_ffmpeg.py` first tries signed
packages from Ubuntu's official archive with strict wall-time bounds, then
falls back to the runner's configured apt sources (also bounded). It never
suppresses installation failures or skips codec/filter assertions. Offline
tests in `tests/test_ffmpeg_ci_install.py` inject subprocess behaviour:
**do not run apt/sudo from pytest**. If FFmpeg integration CI fails, inspect
the installer step independently of playback regressions and record which
signed mirror failed. This is a bounded CI reliability slice of P0 #19.

**Explicit network diagnosis (P0 SC-007):** `smoothcast --network-check
<private receiver IPv4>` is a local, GTK-free troubleshooting command. The
route and Cast-port probes are allowed only after the user invokes it.
`tests/test_network_routes.py` injects fake UDP sockets, TCP connections,
OS route outputs and HLS responses; running pytest never sends LAN packets.
A successful local loopback check must never be described as receiver-side
inbound reachability, nor is VPN/firewall causation proven without a second
host. Keep printed private IPs out of exported support bundles.

**Installed-artifact integrity (P1 SC-097):** the `installed-artifact` CI
matrix builds a source distribution, builds a wheel **from that sdist**, then
installs the wheel without source-tree imports or editable mode into a fresh
Python venv. `scripts/ci/verify_installed_artifact.py` verifies the
`smoothcast`, `sc` and `smoothcast-gui` command entry points (version
command only), canonical version metadata, byte-identical bundled icon, and
importable HLS helper from a different working directory. The script clears
`PYTHONPATH`, display variables and desktop session addresses before
running any installed code. This is a Python/package compatibility check,
**not** native GTK, FFmpeg or receiver playback validation. The checked icon
lives in `src/smoothcast_assets/local.cast-control.png`, not relative to a
Git checkout.

**P0 early Cast preparation safety (#13):** missing selected subtitles or an
undiscovered DLNA renderer must reject the new cast without clearing the
original active receiver's session, playback clock or audio monitor.
`tests/test_cast_preflight_preservation.py` executes the real GUI handlers
with injected objects and no GTK or TV commands. Full retry/alternate
encoding/device tests and physical receiver verification are separate.

**Film screenshot ownership (#140):** select the active receiver/decoder/preview
clock only when its source matches the currently loaded film. The GTK-free
`src/screenshot.py` guard rejects foreign casts, unknown timestamps, and
unpreviewed queue rows before scheduling FFmpeg; test with
`tests/test_film_screenshot_selection.py`. Real-device frame qualification
remains separate.

**P0 cross-platform process ownership (#237):** mock process birth time,
user and argv with `tests/test_process_identity_portable.py`; never signal a
real PID in routine tests. Legacy sessions without birth evidence cannot
reattach unverified helper PIDs. Real Windows/macOS runtime checks remain
separate from portable CI.

**Control API (#269):** `tests/test_control_api.py` runs the real `ThreadingHTTPServer` on 127.0.0.1 with an ephemeral port and fake `cli_control.HANDLERS` (restored after every test); it never contacts a receiver or binds a LAN address, and the module is mypy-gated. Never start `smoothcast --control-api serve` from a test.

**Typed models (#249):** `src/progress_model.py` holds the immutable `Progress` snapshot of FFmpeg's progress file (`Session.progress()` returns it; use `.out_time`, `.done`, `.speed_text`, not dict keys) and the `ReceiverInfo` TypedDict for catt's `info` payload. It is mypy-gated; `tests/test_progress_model.py` covers tolerant parsing.

**Cache privacy (#233):** `src/cache_privacy.py` creates or restricts the
SmoothCast cache to mode 0700 on POSIX and atomically replaces session JSON
through an exclusive mode-0600 file. Do not bypass this helper when persisting
private media paths; preserve existing session data if write/fsync/replace fails.
`tests/test_cache_privacy.py` uses temporary directories and simulated
failures only; the symlink and foreign-user guards never touch real user files.

**Optional GTK smoke** is a *separate explicit* action:
`python3 scripts/test_gui_isolated.py`. It requires Xvfb/xauth,
private runtime/configuration, one-use token and isolated credentials.
It quits promptly and forcibly terminates its process group on timeout.
Do not call the smoke runner inside pytest or point it at the active desktop.

**Real-device tests:** require an intentionally available receiver and clear
scope. Never report Chromecast/DLNA, macOS or Windows native playback as
verified from portable CI alone. Check regressions in device ownership,
playlist lifecycle, subtitles/encoding and error paths.

Keep full failing logs available, concise success output, reproducible test
commands and honest untested conditions. Do not misrepresent pending CI as
passed.
