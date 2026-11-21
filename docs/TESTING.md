# Testing SmoothCast

Run the portable suite without opening the application or contacting a real
receiver:

```sh
python3 -m pytest -q tests -n auto
python3 -m compileall -q src scripts setup tests
ruff check src scripts setup tests sc.py setup.py
```

Routine tests must not launch the real GUI, focus the desktop, or control a
television. See [agent testing safety](agents/testing.md) for GUI and hardware
limits.

## Google Cast protocol fake

`fakecast.FakeCastReceiver` is a loopback-only TLS/CASTV2 test receiver. It
supports heartbeat PING/PONG, receiver status and a basic media session. It
does not advertise itself over mDNS, fetch media, or represent a verified
device model. The only profile available now is `generic`.

Run it as a standalone development process with:

```sh
python3 -m fakecast --profile generic --port 8009
```

In tests, use an ephemeral port and always stop it through the context manager:

```python
from fakecast import FakeCastReceiver

with FakeCastReceiver(profile="generic") as receiver:
    # Connect a protocol client to receiver.host and receiver.port.
    ...
```

The fake binds only to `127.0.0.1`. Its checked-in self-signed certificate and
private key are test credentials for local traffic only.

Add a model profile only from documented receiver evidence. Keep sanitized
limits and quirks in the fake, add tests for accepted and rejected media
capabilities, and record real-device discrepancies through the qualification
process in [#208](https://github.com/gmanldn/smoothcast/issues/208). Do not
infer a device capability from a passing fake test.

The current CASTV2 implementation is an initial protocol slice for [#203](https://github.com/gmanldn/smoothcast/issues/203).
It does not yet cover mDNS, the complete CastBackend contract, model profiles,
fault injection or receiver-side media fetching; keep those acceptance items
open until their tests exist.
