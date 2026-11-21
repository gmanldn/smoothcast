# Testing SmoothCast

Run the portable suite without opening the application or contacting a real
receiver:

```sh
python3 -m pytest -q tests -n auto
python3 -m compileall -q src scripts setup tests
python -m py_compile smoothcast
ruff check src scripts setup tests smoothcast setup.py
```

Routine tests must not launch the real GUI, focus the desktop, or control a
television. See [agent testing safety](agents/testing.md) for GUI and hardware
limits.

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
unavailable. Receiver-side playlist/segment fetching is still under development.

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
`unsupported_seek`, `crash_on_commands`, and `reboot()`. Segment-consumption
faults require the receiver-side HTTP fetch path and remain unimplemented.

The CASTV2 fake remains an active slice of [#203](https://github.com/gmanldn/smoothcast/issues/203).
It does not yet cover the complete CastBackend contract or receiver-side media
fetching; keep those acceptance items open until their tests exist.
