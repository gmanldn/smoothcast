# Low-end laptop performance budget (#515)

The figures below are **targets**, not a claim of real-device qualification (track physical verification in #208).

| Property | Reference |
| --- | --- |
| CPU | Two roughly 2.5 GHz cores, about 10 years old |
| Memory | 8 GiB |
| Hardware encoding | None (software H.264) |
| Input | 1080p30 |
| Safe encoder headroom | **>= 1.3x** real-time, i.e. at least 39 encode FPS |
| Receiver's first frame | **< 4 seconds p95** (not yet qualified physically) |
| Below threshold | **720p** software output, saver rate setting |
| Encoder CPU priority | Below desktop; libx264 preset **veryfast** |

The extra 30% headroom is a policy margin for CPU contention, not a promise of zero stalls. The encoder caps high-FPS input at 30 output FPS.

## Automatic policy and manual override

Fresh installations default to an automatic quality selection. **After first paint**, a daemon thread runs a brief synthetic 1080p libx264 probe. The child encoder runs at reduced process priority, not on GTK, with no film, Internet connection, receiver command or GUI focus.

The bounded measurement is saved to a private cache file named low-end-probe.json under the XDG cache directory. The record contains only FPS, an expiration timestamp and a hash of CPU/OS/FFmpeg identity: replacing FFmpeg or changing hardware requires another probe. Positive measurements last 30 days; failed probes back off for two hours. Missing FFmpeg, malformed cache and unexpected failures select the conservative saver tier.

At cast time, the background worker chooses balanced quality only when measured 1080p encode speed meets 1.3 times the output source FPS. Otherwise it selects saver, **with actual 1280×720 maximum output** on software paths, including bitmap subtitle overlays. Smaller sources are not upscaled. Existing output ownership, subtitle timing, HLS generation and safe receiver validation are unchanged.

Preferences → Playback has an **Automatically choose video quality** switch. Turn it off to use a manually chosen High, Balanced or Data saver tier; any explicit dropdown selection also disables automatic mode. Existing saved configurations are migrated defensively: an old saved quality without the automatic flag remains manual rather than being unexpectedly overwritten.

## Reproducing with Linux CPU affinity

Select two *permitted* logical CPU IDs (check with taskset -pc $$). A full synthetic run records FPS, headroom, chosen tier and benchmark wall time:

~~~sh
python3 scripts/low_end_probe.py --cpus 0,1 --output /tmp/smoothcast-low-end.json
~~~

The helper requires FFmpeg, taskset and nice. It constrains the **child** encoder and never changes desktop priority, touches user media or contacts the LAN. On systems where logical CPUs 0/1 are unavailable, supply other allowed IDs. Additional constraints may be applied with cpulimit or a container cgroup, but neither faithfully models an older CPU's instruction throughput, cache and memory bandwidth.

The Fake Cast reliability report includes the low-end scenario as **informational metadata**, never as proof that a 10-year-old laptop met the performance target. A qualifying physical test must report real hardware, frame latency p50/p95, buffering/stalls, source characteristics, receiver model and actual output resolution. Real-device qualification remains #208.
