# Browser-to-mesh transfer sessions (#569)

Contract: `src/transfer_session.py` (pure; not yet wired into `portal_uploads`, which stays the live API behind a feature flag until end-to-end tests pass).

| Call | Purpose | Codes |
|---|---|---|
| `POST /api/transfers` | `{intent: add\|play\|queue\|copy, client_op_id, name, size, media_type?, digest?, target?: {node, room}, early_stream?}` | 201 new, 200 duplicate op, 400, 404 unknown target, 409 target offline / op reused, 413, 429, 507 |
| `GET /api/transfers/<id>` | status | 200, 404, 410 expired |
| `HEAD`/status for resume | restart at `durable_bytes` | 200 |
| `PUT /api/transfers/<id>/data` | sequential chunk at `received_bytes` | 200, 409 offset_mismatch, 413, 416 |
| `POST /api/transfers/<id>/finalise` | verify digest, make ready; idempotent | 200, 409, 422 |
| `DELETE /api/transfers/<id>` | cancel | 204, 409 |

Errors: `{"error": code, "message": plain text}`. Other owners' sessions return 404. No path leaves the server.

States: negotiating → transferring → buffering → ready → playing → completed; failed and cancelled are terminal.

Budgets: 32 GiB per file, 64 GiB pending in total, 4 active per browser, 16 active overall, 8 MiB chunks, one chunk at a time, 2 h idle expiry.

Routing: `copy` requires a chosen target; otherwise the least-loaded online peer is chosen. If a target disappears, a non-copy transfer with durable bytes (or none sent) moves to another peer as a `relay` without re-upload; otherwise it fails with `target_lost`.

Guards: LAN-only and Host/Origin checks (`guard`) apply to every route.
