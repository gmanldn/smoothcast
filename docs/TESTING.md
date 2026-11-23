# Testing SmoothCast

## Optional manual validation

The project owner has opted for **fast, direct agent commits to `develop`**.
Tests are not a push prerequisite, and the `Verify SmoothCast` workflow is
launched by `workflow_dispatch` rather than on each push. This optimises
commit throughput but increases the risk of regressions; an untested commit
must be labelled **unverified** rather than green.

When validation is requested, use targeted headless checks first:

```sh
python3 -m compileall -q src scripts setup tests
python3 -m py_compile smoothcast
ruff check src scripts setup tests smoothcast setup.py
mypy
python3 -m pytest -q tests/test_relevant_feature.py
# Optional large/manual verification run:
python3 -m pytest -q tests -n auto
```

`python3 scripts/agent.py ship --skip-checks` performs a fast unverified
fast-forward push; plain `ship` retains optional affected checks.
Never open or focus the real GUI, control a television, or treat green
automated tests as physical-device qualification. See
[agent testing safety](agents/testing.md).

## Google Cast protocol fake

`fakecast.FakeCastReceiver` is a loopback-only TLS/CASTV2 test receiver. It
supports heartbeat PING/PONG, receiver status and a basic media session. Its
`generic` profile accepts any declared test stream; model profiles apply the
documented codec, level, resolution and frame-rate limits summarized in
[Google Cast Supported Media](https://developers.google.com/cast/docs/media).
They model rejection behavior with the Cast `LOAD_FAILED` error code
`MEDIA_SRC_NOT_SUPPORTED`; they do not certify a physical receiver or display.

Available profiles: `chromecast-gen2`, `chromecast-gen3`, `chromecast-ultra`,
`chromecast-with-google-tv`, and `google-tv-streamer`. mDNS is opt-in for an
in-process receiver (`advertise=True`) and enabled by the standalone CLI. It
advertises `_googlecast._tcp.local.` on loopback only with Cast TXT fields. The
discovery test is marked `multicast` and skips cleanly when local multicast is
unavailable. Finite HLS playlists and segments are fetched from loopback HTTP
only; content types, byte ranges and CORS response headers are checked. The
fake reports buffering, per-segment progress and `IDLE/FINISHED` at the end of
a finite playlist. It does not fetch URLs that resolve outside loopback.

Run it as a standalone development process with:

```sh
python3 -m fakecast --profile chromecast-gen2 --port 8009
```

In tests, use an ephemeral port and always stop it through the context manager:

```python
from fakecast import FakeCastReceiver

with FakeCastReceiver(profile="chromecast-gen2") as receiver:
    # Connect a protocol client to receiver.host and receiver.port.
    ...
```

The fake binds only to `127.0.0.1` and advertises only on that interface. Its
checked-in self-signed certificate and private key are test credentials for
local traffic only.

Model limits live in `fakecast/profiles.py`. Add `CodecLimit` entries only
from documented receiver specifications. A fake stream is passed through
`media.customData.fakeStream` with `codec`, `profile`, `level`, `width`,
`height`, and `fps`. For each profile, test a stream at its documented limit
and an out-of-spec stream; the latter receives a `LOAD_FAILED` response.
Record physical discrepancies through [#208](https://github.com/gmanldn/smoothcast/issues/208).
Do not infer device qualification from a passing fake test.

Fault injection is available through `answer_heartbeats`, `delay_command()`,
`error_command()`, `drop_connection_on()`, `stale_media_session`,
`unsupported_seek`, `crash_on_commands`, `slow_segments()`, and `reboot()`.

The CASTV2 fake remains an active slice of [#203](https://github.com/gmanldn/smoothcast/issues/203).
It does not yet cover the complete CastBackend contract; keep that acceptance
item open until both adapters pass the shared contract suite against it.

## Mesh simulator (`tests/mesh_sim.py`, ticket #395)

Mesh layers are written against the narrow `Clock` and `Transport` ports in
`src/mesh_ports.py` and tested in a deterministic discrete-event simulator: a
virtual clock in integer milliseconds, a seeded RNG, no sockets, threads or
sleeps. Minutes of network time run in milliseconds and a seed always produces
the identical event log.

```python
world = SimWorld(seed=7)               # default node: the naive ToyGossipNode
nodes = world.join(5)
world.assert_converged(within_ms=3000)
world.partition(nodes[:2], nodes[2:]); world.run(10); world.heal()
world.assert_converged(3000)
world.assert_budget("leave_clean_s", world.measure_leave(nodes[0], clean=True))
print(world.report())                  # p50/p99/max per metric, egress per node
```

- **Faults:** `stop(clean)`, `crash`, `restart`, `sleep`/`wake` (monotonic time
  pauses, wall time jumps, overdue timers run on wake), `change_ip`,
  `partition`/`heal`, `set_multicast`, `set_loss`, per-link latency/jitter/loss/bandwidth.
- **Plug in a real node** with `SimWorld(seed, factory=...)`. The factory receives
  `node_id, boot_id, name, clock, transport, rng, boot_epoch` and returns an object
  with `start`, `stop(clean)`, `local_key`, `records`, `target_ids`, `add_target`
  (`NodeUnderTest`). Optional `on_wake` and `on_address_changed` hooks are called.
- **Budgets** (`BUDGETS`) mirror `docs/MESH_DESIGN.md`; egress means bytes a node
  *sends* per second (multicast counted once); ingress is reported separately.
- **Property runs:** `run_seeds(range(100), random_scenario, factory=...)` applies
  random churn, heals, settles and returns failures: non-convergence, dead nodes
  still listed, old boots held, caps exceeded.
- **Model limits:** independent links (no shared-medium contention), RPC loss is
  modelled as retransmission delay, CPU is not simulated. Real networks are
  qualified separately under #208.
