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
exercise the persistent PyChromecast adapter in isolated checks; `catt` remains
the default until the protocol-level fake receiver and full parity checks pass.
The adapter is not yet complete for long-drop reconnects or every receiver
quirk, so issue #202 remains open.
