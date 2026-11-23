# Reliability measurements

Session summaries are opt-in diagnostic data. SmoothCast stores them locally
in `reliability.json` under the per-user `cast-control` configuration folder.
The store keeps at most 100 records from the latest 30 days and is written
atomically with owner-only permissions. Its allow-list excludes media paths,
titles, receiver names, addresses, URLs, and credentials. `smoothcast
--diagnostics` includes only the same bounded summaries; no metrics are sent
over the network.

## Session indicators

| Indicator | Start and stop event | Meaning |
| --- | --- | --- |
| Cast success | Cast attempt starts; result is completed, stopped, replaced, failed or interrupted | Outcome counts are the denominator/numerator source; replaced/interrupted are reported separately. |
| Time to receiver PLAYING | Cast click to the first status poll reporting `PLAYING` | This is receiver-confirmed PLAYING latency, not a decoded first-frame measurement. Missing confirmation stays null. |
| Playing time | Sum of poll-observed intervals whose previous state was `PLAYING` | Bounded by the first and last receiver state observations. |
| Buffering time | Sum of poll-observed intervals whose previous state was `BUFFERING` | Divided by observed PLAYING + BUFFERING time for stall ratio; null if neither state was observed. |
| Rebuffer count | Transition into `BUFFERING` after any `PLAYING` observation | The initial buffer does not count as a rebuffer. |
| Seek latency | No value is currently emitted | Requires a confirmed post-seek PLAYING position before this indicator is meaningful. |
| Recovery time | No value is currently emitted | Will be populated with a chaos-suite recovery event and budget. |
| CPU, RSS, disk and orphan count | No values are currently emitted | These need measured process sampling and leak-detector ownership before targets are set. |

State intervals use `time.monotonic()` and are accumulated on the existing
status callback; there is no polling, disk access, or receiver command added to
the GTK thread. JSON persistence runs in the existing media worker domain.
Unknown measurements remain null rather than being guessed. The metric is
about a status poll, so its resolution is bounded by the configured polling
interval; it must not be compared directly with camera-measured first-frame
time.

`reliability_metrics.dashboard_summary()` provides the data-only hook for the
release qualification dashboard (#59): bounded sample count, outcome/protocol/
mode counts, and medians for confirmed-PLAYING latency and observed stall
ratio. It contains no per-session rows or receiver/media identifiers.

## Fake receiver benchmark

Every Verify run measures seven loopback CASTV2 commands from dispatch until
the fake receiver confirms `PLAYING`. `scripts/reliability_benchmark.py`
emits the seven samples, median, Python/runner profile and comparison status as
JSON. GitHub Actions uploads the report as a 30-day artifact. The gate compares
only the same `ubuntu-24.04-py3.13` profile and allows a 100% median increase
until repeated CI runs provide enough evidence to tighten the margin. A
profile mismatch is reported without comparing unrelated machines. This fake
measures protocol/status latency only; it does not claim physical-device
time-to-first-frame or playback success.

The first matching-run artifact is the baseline source. Check in its profile
and median as `docs/reliability-baseline-ubuntu-24.04.json`; do not substitute
a developer workstation measurement. Targets for physical playback, recovery,
resource cost and orphan count remain unset until the real-device and chaos
fixtures produce dated evidence.

## Idle UI timer budget (#443)

Visual playhead and meter callbacks exist only while playback is active and
the GTK window is mapped (500 ms and 100 ms respectively). Actual GdkSurface
width/height notifications coalesce responsive reflow; there is no 200 ms
resize polling. Device status checks run every 4 seconds during playback or
while the active window is in focus, reducing to 30 seconds while idle.
MPRIS refreshes on playback and control changes. Its fallback refresh
runs every second in focus or during playback and every 30 seconds while idle
and hidden.
The room activity view refreshes every 15 seconds when hidden, instead of
once per second. Sleep and fade timers run only while armed or awaiting a
receiver-volume restore. All visual timer sources are removed on window close.

The GTK-free test in tests/test_idle_timers.py counts the expected GLib timer
callbacks over a simulated hidden, idle minute (including existing LAN/theme
checks) and enforces at most one wakeup per second. This is a *scheduler*
budget, not a physical CPU/battery benchmark; only isolated Xvfb tests may
exercise GTK, and physical receivers need separate qualification.

Hidden transcoding sessions retain a separate 1-second stall-watchdog tick;
only the visual seekbar and audio-meter callbacks stop. This preserves HLS
recovery during minimised/hidden playback without waking an idle window.

## Startup budget (#463)

The window should be interactive in under 800 ms on reference hardware. Two
guards keep it that way:

- **Import gate** — `python3 scripts/ci/import_budget.py` (CI job *Startup
  import budget*, every push) imports the GUI entry module with
  `-X importtime`, opens no window, and fails if a heavy module loads at
  startup (`zeroconf`, `pychromecast`, `PIL`, `requests`, `catt`, the library
  index/search/replica stack, …), if more than 460 modules load (394 before this
  work, 387 now), or if the import takes over 3 s. Heavy modules load on first
  use (`peer_discovery` resolves zeroconf lazily; `cast_portal_host` imports the
  library stack only once a library folder exists). Add a new heavy dependency
  to the denylist rather than raising the budget.
- **Timeline** — `startup_timeline` records `activate`, `window_built`,
  `presented`, `first_frame` (GTK's first completed paint), and `interactive`
  (the next main-loop idle dispatch). Values are elapsed milliseconds from the
  Python GUI entry before native imports. The desktop diagnostics bundle
  includes these milestones under `startup` alongside the 800 ms target.
  The isolated GTK runner prints the milestones for its Xvfb environment.
- **Deferred startup** — Portal, discovery, receiver timers, MPRIS and the update
  check start at low idle priority after the first paint and interactive mark.
  Primary-instance cleanup still runs before window creation and session adoption.

## Control latency (#466)

How fast a tap feels, measured against the real portal with a fake receiver
that confirms after 30 ms (a quick LAN Chromecast). One phone taps while the
others poll status like the web remote does. **ack** is tap to "the portal
accepted it"; **confirmed** is tap to the new receiver state showing in
`/api/status` (browser push delivery and the real receiver's own delay are not
included). SLOs: ack p95 under 100 ms, confirmed p95 under 1 s.

| Phones in the room | Action | ack p50 / p95 (ms) | confirmed p50 / p95 (ms) |
| --- | --- | --- | --- |
| 1 | next | 1.9 / 7.2 | 36.7 / 44.3 |
| 1 | play_pause | 2.0 / 12.6 | 37.3 / 56.0 |
| 1 | seek | 2.0 / 8.7 | 37.1 / 49.9 |
| 1 | volume | 1.9 / 5.1 | 36.6 / 48.9 |
| 32 | next | 2.0 / 27.2 | 39.1 / 98.6 |
| 32 | play_pause | 2.7 / 17.5 | 39.3 / 86.4 |
| 32 | seek | 2.0 / 13.7 | 38.1 / 57.8 |
| 32 | volume | 2.2 / 9.4 | 37.5 / 64.9 |
| 8 | next | 1.6 / 7.8 | 36.6 / 44.6 |
| 8 | play_pause | 1.7 / 8.4 | 36.2 / 44.9 |
| 8 | seek | 1.9 / 10.0 | 37.0 / 46.9 |
| 8 | volume | 1.8 / 8.9 | 36.7 / 41.1 |

Baseline: `docs/control-latency-baseline.json` (15 rounds per action, Python
3.13.5). The gate (`tests/perf/test_control_latency.py`, CI job
*Search performance gates* in the full lane, slack 3 for shared runners) fails
on an SLO breach or a p95 more than 20% over the baseline (never tighter than
+25 ms, which is timer noise). Run it with
`python3 scripts/control_latency_benchmark.py --check docs/control-latency-baseline.json`;
refresh the baseline after an intended change with `--write-baseline`.

## Soak (#464)

`scripts/soak.py` runs the real portal on loopback with a fake receiver, 31
polling phones (the room caps at 32 with one visitor seat), a 500-item queue and
a fake clock that advances 30 s per cycle, so 2,000 cycles are about 17 simulated
hours. Each cycle polls, seeks, votes, edits the queue, sometimes uploads a tiny
file, and has a visitor join and leave. Every 10 cycles it samples threads, open
FDs, RSS, scratch files and the size of every bounded map.

The verdict is deliberately not flaky: after a 20% warm-up **threads and FDs may
not grow at all** and **every bounded map must stay under its designed cap**
(sessions 128, participants 32, dormant 128, events 200, command cache 512,
limiter 512, ...). RSS growth and upload retention only warn. A thread, FD or
unbounded-map leak injected on purpose is caught by `tests/test_soak_smoke.py`.

```sh
python3 scripts/soak.py --cycles 150                       # ~15 s: smoke
python3 scripts/soak.py --cycles 2000 --report soak-report.json   # nightly size
```

The *Soak nightly* workflow runs the long version daily and uploads
`soak-report.json` (the full time series and summary) as an artifact.
