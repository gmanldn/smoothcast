# Adding a fake DLNA renderer profile

Use this guide when a real television reveals a repeatable DLNA quirk.

1. Capture only traffic from a device you are authorized to test. Record the
   service/action, relevant headers and status codes, media range behavior,
   reported position format, and any timing that changes playback.
2. Remove IP and MAC addresses, serial numbers, media URLs and tokens, titles,
   file paths, and account data. Do not commit raw packet captures.
3. Add a concise name to `FakeDlnaRenderer.PROFILES`. Model the smallest
   behavior in `_serve_ssdp`, `_perform`, or `fetch_media`; keep sockets bound
   to loopback and add a regression test that runs real `dlna` code against it.
4. Assert that SmoothCast handles the behavior or returns a useful error. Keep
   control and media requests in `tests/test_fake_receivers.py`; add sanitized
   fixtures only when the test needs a captured XML or SOAP response.

Run the focused fake-receiver tests and the full headless suite. Loopback
results improve deterministic coverage but do not replace testing on the
capturing television.

## Google Cast backend boundary (#202)

`castctl.CastBackend` currently abstracts discovery, status and commands;
`CattBackend` preserves the existing CLI adapter. `tests/test_cast_backend.py`
checks that boundary headlessly. Set `SMOOTHCAST_CAST_BACKEND=pychromecast` to
exercise the persistent PyChromecast adapter in isolated checks; its single
mDNS browser and receiver connections use PyChromecast's five-second reconnect
retry. Status callbacks reach the UI through the GTK main loop, and receiver
changes or window close release the active subscription. `catt` remains the
default and polling fallback until protocol-level fake receiver coverage and
device-specific parity are established by issues #202 and #203.

The loopback TLS/CASTV2 fake lives in the top-level `fakecast` package. It
covers a persistent PyChromecast sender connection, heartbeat, receiver status
and basic media commands. Its five model profiles summarize Google's published
codec and resolution limits; they are fixtures, not real-device qualifications.
The fake advertises `_googlecast._tcp.local.` on loopback only with the Cast
TXT fields. It fetches finite HLS playlists and segments from loopback HTTP,
checking MIME types, byte ranges and CORS headers. Media URLs resolving off
loopback are rejected. See [Testing SmoothCast](../TESTING.md) and issue #203
for the current scope.

Protocol fault tests can set `answer_heartbeats = False`, use
`delay_command()`, `error_command()` or `drop_connection_on()` for a named
CASTV2 command, set `stale_media_session` or `unsupported_seek`, add a command
to `crash_on_commands`, and call `reboot()` to disappear and return on the same
loopback port. These are deterministic transport/session faults; segment
consumption faults wait for receiver-side HTTP media fetching.
