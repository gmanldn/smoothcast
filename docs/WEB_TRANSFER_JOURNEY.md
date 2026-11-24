# Browser file-transfer journey and authoritative progress

Owner goal: a first-time browser guest understands what is happening when
sending a film or track, where the bytes go, and when it reaches Up Next or
requests room playback. Source: `src/portal.py`; #570 and #324.

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
