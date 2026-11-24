# SmoothCast node-to-node HTTP protocol

Status: documents what is implemented today for **library sharing** and **file
streaming** between nodes. Membership, gossip and mesh state are described in
[MESH_DESIGN.md](MESH_DESIGN.md); browser/remote endpoints are in the OpenAPI
description ([api/openapi.json](api/openapi.json), also served at
`/api/openapi.json`). Trust model: the home LAN ([VISION.md](VISION.md)); every
node refuses clients outside private, link-local and loopback ranges.

## Library replication (`search.v1`)

Each node owns its index; peers hold read-only replicas
([MESH_SEARCH.md](MESH_SEARCH.md)).

| Route | Purpose |
| --- | --- |
| `GET /mesh/library/generation` | `{origin, epoch, seq, count, caps}`; cheap change detector |
| `GET /mesh/library/changes?epoch=&since=&limit=` | ordered `upsert`/`delete` rows after `since`; **410** with the current `epoch` when the epoch changed or history was compacted |
| `GET /mesh/library/snapshot?cursor=&limit=` | paginated shared entries with `epoch` and `at_seq`; continue with `changes` from `at_seq` |
| `GET /mesh/library/search?q=&limit=` | live query against this node's shared library only |

Rules every implementation must follow:

- Pages are at most 5,000 entries; a node serves one snapshot stream per client
  at a time and answers **429** with `Retry-After` beyond ~10 requests/s.
- Responses may be gzip-compressed when `Accept-Encoding: gzip` is sent.
- Only **shared** folders are served. Entries carry `folder_label` and a
  relative `rel_path`; absolute paths, inode numbers and mtimes never leave the
  node.
- Appliers validate every entry (`library_replication.validate_entry`: required
  `content_key`/`kind`/`title`, strings at most 512 characters, no nested
  values) and discard a malformed page.
- Timestamps are node-local; replicas expire by their own receive time, so clock
  skew between nodes is harmless.

## File streaming

`GET|HEAD /mesh/file/<content_key>` returns ranged bytes (`Range`, suffix
ranges, `416`). A node serves the file itself when it is in a shared folder;
otherwise it proxies to an online peer whose replica lists the key, forwarding
the `Range` header and resuming from the exact byte offset (up to three retries)
if the peer drops mid-stream. A proxied request carries
`X-SmoothCast-Hop: 1`; a node receiving it never proxies again. At most eight
streams per node run at once (**503** beyond).

## Evolving the protocol

Add fields, never repurpose them; unknown fields must be ignored and preserved
when re-serving. Gate new behaviour on a capability name (e.g. `search.v1`) in
`/mesh/library/generation`, and bump the epoch rather than changing the meaning
of an existing row. Version negotiation across the wider mesh is tracked in #387.


## Acquisition observations (mesh.acquisition.telemetry.v1)

Read-only cross-node progress, independent of the v1 record digest and queue
authority (#589). A node advertises the **acquisition-telemetry-v1** discovery
hint; this is not permission to submit, cancel or fetch media. The separate
protected `acquisition_status` RPC exchanges bounded hello objects and requires
both peers to negotiate `mesh.acquisition.telemetry.v1`. The responder checks
the requester's current membership, source IP, node and boot IDs, intended
recipient node and boot, and the per-peer capability kill switch. This is
the existing trusted-LAN transport, **not** cryptographic authentication;
remote mutations must use stronger explicit peer authorisation.

A reply carries the responder's node/boot IDs, hello, and at most four active
jobs, each with an opaque job ID, source kind, stage, received bytes, total
bytes and measured rate (null when unknown). No titles, source URLs, infohashes,
filesystem paths, session tokens, peer IPs or external-tool messages are sent.
No job control or content transfer is exposed by this RPC.

Polling is bounded to two in-flight requests across the node, with a
one-second scheduler, two-second successful refresh interval and five-second
failure backoff. Responses must match the current peer endpoint and boot.
A failed or more than 12-second-old observation is stale, not counted as live;
last measurements are retained for at most 40 seconds. Departures, boot
changes, endpoint changes and disabled capabilities discard old observations.
The authenticated room status/SSE includes the separate `mesh_link_activity`
field with per-node freshness, at most 32 displayed jobs, and an explicit
omission count. An unavailable observation is never treated as an empty
successful report. Legacy peers remain compatible without this capability.

Headless real loopback verification is in
`tests/test_mesh_acquisition_activity.py`. Remote worker assignment, persistent
job fencing, remote cancellation and verified file delivery remain separate
work on #589; telemetry alone does not establish that a remote download can be
assigned or that a file is playable.
