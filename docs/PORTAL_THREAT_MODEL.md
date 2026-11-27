# Portal trust model and authorization boundary

Scope: the LAN room portal in `src/portal.py`, `src/portal_screens_http.py`,
`src/portal_mesh_http.py`, `src/api_spec.py`, `src/portal_uploads.py`. Trust
model: the **trusted home LAN** (docs/VISION.md#trust-model-the-trusted-home-lan).
Anyone who can reach the selected private LAN interface can see the login page;
with joining open by default, anyone on that LAN can control playback unless the
House PIN is enabled.

## Attackers considered

| Attacker | Example |
| --- | --- |
| Buggy or hostile device on the LAN | sends garbage HTTP, floods requests, replays old cookies, spins up many browser guests |
| Misconfigured clone | copied room config gives two hosts one stable entry name or one PIN |
| Hostile web page in a guest's browser | CSRF, DNS rebinding, cross-origin requests; cannot forge the session cookie or the per-session CSRF token |
| Out of scope | a hostile resident, a shared office/dorm network, the internet |

## What a session guarantees

- Joining (`POST /api/login`) returns an HTTP-only, same-site session cookie
  and a per-session CSRF token.
- State-changing requests require the session cookie **and** the CSRF token and
  a matching Host/Origin header (docs/LAN_PORTAL.md#security-and-limits).
- Routes are additionally gated by the declared capability in
  `src/api_spec.py` (`ROUTE_CAPABILITIES`): `room:read`, `room:write`,
  `media:read`, `mesh:read`, `uploads:create`, `uploads:manage`,
  `link:acquire`, `link:search`, or `None` for public read-only routes.
- Media is addressed only by opaque queue IDs; host paths never reach a browser.
- Revoking a guest drops their screens and media reads immediately.

## Defences

- **Authentication boundary.** Public routes (`/`, `/api/config`, `/api/login`,
  `/api/openapi.json`, `/silence.wav`, `/screen`, `/nodes`, mesh library reads)
  need no cookie. Everything else requires a valid session.
- **CSRF + Host/Origin.** Every state-changing request checks the CSRF token
  and the allowed Host/Origin.
- **Per-participant rate limits.** Token buckets per authenticated participant
  (room reads, mutations, upload control/chunks); exceeding a budget returns
  HTTP 429 with `Retry-After`.
- **Bounded concurrent commands.** At most two outstanding commands per
  participant; one guest cannot monopolise the shared queue.
- **Media serving limits.** At most 8 concurrent streams and 2 conversions per
  room; symlinks, directories and vanished files are refused at open time.
- **Upload containment.** Mode-0700 cache directory, mode-0600 partial files,
  at most 3 active transfers, 512 MiB free-space reserve, fsync per chunk,
  content-range validation, no whole-file in memory.
- **Off-thread status.** `GET /api/status` reads a GTK-published snapshot, so a
  busy UI never makes phone polling block.

## Residual risks (accepted)

- The room is plain HTTP on a trusted LAN. Anyone on that LAN segment can see
  media sent to a screen in the same way as the dashboard.
- On an open room, being on the Wi-Fi is the invitation; the House PIN becomes
  the room authority when enabled. Keep the desktop screen and any House PIN
  private; closing SmoothCast stops the listener.
- Capability declarations are documented policy and the contract test keeps
  them in step with the routes; enforcement at the dispatcher is tracked
  separately (issue #702 remaining slices).
