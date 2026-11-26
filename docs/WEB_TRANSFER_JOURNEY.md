# Browser file-transfer journey and authoritative progress

Owner goal: a first-time browser guest understands what is happening when
sending a film or track, where the bytes go, and when it reaches Up Next or
requests room playback. Source: `src/portal.py`; #570 and #324.

## Upload & Cast Now

The joined home screen presents a primary **Upload & Cast Now** action. The
guest chooses one video, then the connected room authority (pnode) checks its
selected receiver from GTK-owned status without a network call on the GTK
thread. No bytes are sent before the guest confirms the named receiver.
The confirmed target is checked again before reserving upload storage and is
pinned server-side to the upload ID for early and final dispatch, including
resumes. A changed target is refused rather than silently retargeting the
guest's upload. Queue-only and audio uploads retain their existing behaviour.

The existing 16 MiB progressive heuristic remains the initial buffering
mechanism for suitable video containers. It is not a proven continuous
producer/consumer pipeline; full mesh routing, sustained-underflow recovery,
and physical playback qualification remain #571/#572. The pnode here is the
connected room authority, not an assertion that arbitrary peer ingress is
already routed to the elected mesh primary.

## Current staged journey (supported on develop)

| UI stage | Actual authority | Honest outcome |
| --- | --- | --- |
| Choose media | Local `<input type=file>` or drag/drop; browser retains the source file | No bytes sent |
| Prepare | `POST /api/uploads` reserves a private host upload; the client records a bounded file fingerprint for matching resume | Session allocated on the connected host |
| Transfer | Sequential `PUT /api/uploads/<id>` with Content-Range; reply's `received` field determines progress | Host acknowledges durable bytes; do not use optimistic bytes or count network requests as progress |
| Check media | After all bytes acknowledged, `POST /api/uploads/<id>/complete` checks/finalises media before dispatch | 100% **bytes** does not mean the queue/playback is complete |
| Queue / play | Completion response acknowledges dispatch request; default is shared Up Next | Queue acceptance or a **playback request**; no receiver-confirmed PLAYING claim |

The UI shows byte count, integer percentage, measured/smoothed rate and a
deliberately approximate ETA calculated only from server-acknowledged bytes.
Until measurements exist, the UI says `Measuring speed…` and
`ETA calculating…`. It has an accessible current-stage marker, readable
mobile-width controls, reduced-motion support and an ARIA status region.

The current honest route is **Your device → SmoothCast host → Up Next / room
receiver (pending)**. The browser does **not** invent mesh peer names, cross-
node copy percentage, transcode progress or receiver readiness. The connected
host can already perform some early cast heuristics; readiness and actual
receiver confirmation remain separate. Audio is always queue-only.

Uploads are sequential and host-authoritative. Pause aborts the current
request and stops its retry loop; the guest retains the local file and can
resume after reselecting the identical file. Reconnection performs a new
authenticated status GET and resumes at the server's `received` offset,
not the guessed client cursor. Cancellation uses the existing DELETE route.
Keep the existing cookie, CSRF/Origin checks, quotas and private partial files.
Never display server absolute paths to a guest.

## Follow-up mesh journey — not yet implemented

The desired full multi-node experience requires #569 (session contract), #571
(route choice), #572 (bounded growing-file playback), and #570 (frontend).
Do not ship UI milestones on speculation: each new mesh stage needs a bounded,
versioned backend status with an authoritative source, target, bytes, attempt
number, state, timestamp, failure and privacy-filtered display labels.

Proposed states: negotiating → browser transfer → optional node relay or
transcode → media ready → dispatch requested → receiver-confirmed playback.
Only show stages actually negotiated for the particular intent/route. A route
change must explicitly replace the old leg; it must not make progress run
backwards or claim completion of an abandoned peer. Distinguish bytes on the
browser-host leg from bytes on a host-node leg and from playback buffer.
Treat unknown status as unknown, not success.

The shared queue remains authoritative under `queue_revision` and
`queue_command_id`. The web UI exposes Play now, Play next, move earlier/
later, vote and remove as distinct labelled actions; the server resolves
conflicts and reports acceptance. Do not interpret command acknowledgement as
receiver-confirmed playback.

## Verification

Run the compact headless browser contract:

```sh
python3 -m pytest -q tests/test_portal_transfer_journey.py
```

Existing integration coverage: `tests/test_portal.py`,
`tests/test_portal_uploads.py`, `tests/test_portal_queue.py`, and
`tests/test_portal_guest_ux.py`. Visual and touch qualification at
320/768/1440 px, two-phone reconnect and real mesh route reporting remain
open in #570/#569. Do not mark those tickets completed on this UI slice alone.


## Guest upload smoke (P0 #586)

The fast test exercises the actual HTTP listener, open join, browser-compatible
build/CSRF headers, chunk upload, an injected storage error, status/resume,
exact staged SHA-256, forced audio queueing and idempotent completion. It
stubs the media probe only to keep the transport check independent of the
machine's codec installation. It is included in the manual Verify workflow.

```sh
python3 -m pytest -q tests/test_portal_guest_upload_smoke.py
```

Running tests with `-n` needs the development test dependencies (including
`pytest-xdist`, listed in `pyproject.toml`); without them pytest stops with
`unrecognized arguments: -n` before any test runs.

For the real-browser qualification, install the optional test-only Playwright
package and its Chromium runtime into the development environment (FFmpeg and
FFprobe must also be installed). The following runs the actual served page,
mobile-width viewport, open join, native browser file selection, XHR transfer,
automatic retry, real audio validation, queue and video-playback requests,
and exact stored-byte checks. Desktop dispatch is a recording fake: no actual
receiver or GTK session is started.

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
SMOOTHCAST_BROWSER_SMOKE=1 python3 -m pytest -q tests/test_portal_guest_upload_smoke.py
```

The browser test is deliberately skipped unless explicitly opted in; a missing
browser or FFmpeg dependency fails the opted-in test rather than silently
passing. Neither test needs a router, mDNS, UPnP, a TV, external network
access, or personal files. Actual TV playback and another device's access to
the running host remain separate acceptance checks.

### LAN diagnosis (no UPnP router mapping)

* If the guest cannot open the room, use the host's numeric private LAN URL
  (including the advertised port), check same-network Wi-Fi, guest/AP/client
  isolation, VPN routing, and host firewall rules for the LAN listener.
* If the page opens but a transfer fails, inspect Live transfer monitor:
  HTTP status, current operation, last host-confirmed offset, elapsed time,
  and newest-first events. Check storage capacity and permissions. Browser
  bytes sent do not prove that the host has durably received them.
* If upload completes but playback does not, distinguish queue admission,
  cast dispatch and receiver confirmation. Check receiver selection and
  host-to-receiver/media-stream reachability; UPnP/DLNA SSDP discovery can
  matter to renderer discovery, not the HTTP upload.
* Never open internet-facing router ports automatically. See the authoritative
  LAN trust boundary in docs/VISION.md.

## Upload failure recovery evidence (P0 #585)

Headless, loopback only; no GTK, receiver or real browser:

```sh
python3 -m pytest -q tests/test_portal_upload_faults.py tests/test_portal_uploads.py \
  tests/test_portal_upload_retry.py tests/test_portal_activity.py
```

Faults are injected at the real `os` layer. Creation (permission, disk full,
read-only), chunk write (disk full after a partial write) and finalisation
(rename or fsync failure) each return an actionable JSON error with no private
path or traceback, keep the durable offset and uploaded bytes, and succeed on
retry. A second finalise is an idempotent replay with exactly one playback or
queue dispatch. A failed dispatch or an immediate receiver rejection does not
poison the accepted-upload cache, so the same upload can be retried. Timeouts
are resumable (408); unknown uploads and bad sessions give their own errors.
If a failure still happens on an installed build, the live upload diagnostic
pane reports the failing stage, HTTP status and durable offset (see #570).
