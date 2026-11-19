# Bounded background work and GTK ownership

SmoothCast uses `src/async_jobs.py::WorkDomains`, via
`cast_widgets.Async.run(work, done=…, failed=…, domain=…, valid=…)`.
Workers are lazily created **daemon** threads with bounded queues and
explicit, non-blocking overload responses. The original `Async.run`
call shape remains supported; unspecified work uses `background`.

| Domain | Workers | Waiting | Intended work |
| --- | ---: | ---: | --- |
| `status` | 2 | 6 | Poll a receiver or verify an existing session |
| `discovery` | 1 | 2 | mDNS/SSDP receiver discovery |
| `transport` | 2 | 8 | Play, pause, seek, stop, explicit URL handoff |
| `media` | 2 | 4 | FFprobe, FFmpeg preparation and HLS restarts |
| `background` | 2 | 8 | General low-frequency actions, reports |

These are limits, **not** measured performance targets. Busy queues reject
rather than block GTK; the optional failure callback receives a short
actionable message via `GLib.idle_add`. Exceptions are logged and delivered
through the same mechanism. The queued and executing work are bounded, but
an already-running FFmpeg or remote network request still needs its own
timeout/cancellation checks.

## Ownership and lifecycle

- Background workers must never access GTK widgets. Only result callbacks
  scheduled on the GLib main context may do so.
- Capture receiver identity, session object and generation before dispatch,
  and retain each caller's existing checks before modifying state. The optional
  `valid` predicate is evaluated on the **main context** just before a
  callback; never use it to skip a callback that must release a live busy lock.
- Polling, discovery, transport and media have separate queues. A slow HLS
  conversion cannot starve receiver status reports.
- The `GApplication` shutdown signal calls `Async.shutdown()`: queued
  work is dropped, new submissions rejected and late callbacks discarded.
  Running daemon tasks cannot keep the user interface process alive, but
  they must retain independent FFmpeg/TV cleanup and bounded timeouts.
- Do not automatically retry a receiver command that may already have
  succeeded. Cancellation and ownership are protocol-specific.

## Maintenance and next targets

`tests/test_async_jobs.py` exercises independent progress, capacity
backpressure, callback-thread ownership, stale validation and shutdown,
without running GTK, probing a LAN or touching the user's TV.

Queue durations are now handled through `src/queue_metadata.py`.
`QueueMixin._enqueue` snapshots missing paths on the GTK thread;
FFprobe returns an independent dictionary from a media worker, and its
GLib callback publishes only still-queued paths without overwriting
newer media metadata. `tests/test_queue_metadata.py` executes that
handler with a thread-bound dictionary and checks cancellation, duplicate
paths and stale results. No worker reads `queue_durations` or widgets.

Next inspect `cast_av.py` for high-frequency volume/mute coalescing,
then add protocol-aware cancellation under issues #16 and #194.

References: [GTK4 threading](https://docs.gtk.org/gtk4/section-threading.html)
and [PyGObject idle callback guidance](https://gnome.pages.gitlab.gnome.org/pygobject/guide/threading.html).
