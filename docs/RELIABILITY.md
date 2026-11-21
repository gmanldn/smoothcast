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
