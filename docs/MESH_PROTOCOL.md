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
