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

### Assignment and fencing rules (#589, pure core)

`src/mesh_acquisition_assignment.py` holds the transport-free rules; no RPC,
no remote job mutation and no file transfer is wired to them yet.

* **Selection:** only a trusted, live, opted-in node with the matching
  provider, a free slot and storage headroom is eligible; remote nodes must
  negotiate `PROTOCOL_VERSION` (0 or absent means no acquisition extension).
  The local node is preferred, otherwise most free space, then node id.
* **One download per source:** the ledger keys jobs by a digest of the
  canonical source, so duplicate submissions share the live job.
* **Fencing:** every assignment has a new generation. Executors reject lower
  generations; the ledger rejects reports from a superseded one.
* **Ambiguity:** an expired lease (or a restart) marks a running job
  *ambiguous*. It is never reassigned until the old executor is confirmed
  stopped or the host explicitly accepts the duplicate-download risk.
* **Exactly once:** completed media is queued by `enqueue_once` only after the
  transferred content key matches; replays and restarts cannot enqueue twice.
* **Redaction:** the public view carries only job id, stage, executor, byte
  counts and stale/ambiguous flags.

### Offer, report and cancel messages (#589, transport-agnostic)

`src/mesh_acquisition_rpc.py` defines the small dict messages (`offer`,
`cancel`, `report`, `finished`, `failed`; wire version 1) and two classes:
`HostCoordinator` (room host, sole queue authority) and `WorkerService`.
Messages are allow-listed, size-bounded and carry only job id, generation,
provider kind and the source digest. The sender is the authenticated peer id
from the transport, never a message field.

* A refused offer (`busy`, `fenced`, `invalid`) returns the job to pending.
* A lost or unintelligible delivery marks the job **ambiguous**; it is never
  reassigned without an explicit resolution.
* A replayed offer is `duplicate` and starts nothing; a stale-generation cancel
  is ignored; a cancel to an unreachable owner reports "unacknowledged".

Covered by an in-process two-node simulation in
`tests/test_mesh_acquisition_rpc.py`. The real authenticated mesh RPC, verified
file transfer and Live Mesh display are still to be wired.

### Authenticated transport for assignment (#589, `mesh.acquisition.assign.v1`)

`src/mesh_acquisition_bridge.py` carries the `mesh_acquisition_rpc` messages on
the protected `acquisition_job` RPC kind. Trust model (LAN, **not**
cryptographic): the sender must be a currently ALIVE member whose node id, boot
id and *numeric source address* match, and both peers must negotiate the
separate `mesh.acquisition.assign.v1` capability (advertised as the
`acquisition-assign-v1` hint only when the app configures a worker or attach
hook; the v1 telemetry token and node digest are untouched). Workers accept
offers/cancels only while the operator's live opt-in (`acquisition_accept`) is
true, otherwise they answer `declined` and the job returns to pending. Reports
from workers are applied to the host ledger under the sender's authenticated
node id. `send` blocks and is refused on the mesh loop thread; a lost or
unverified reply raises, which the host treats as an ambiguous owner. Remote
worker execution and verified file transfer are still to be connected.

### Remote worker execution (#589)

`src/mesh_acquisition_executor.py` is the worker's `start`/`stop` target. An
offer now carries the canonical source identity (`src`: 11-character video id
or 40-hex btih) *only* on the authenticated RPC; it must hash to the offered
`key` and is re-validated against the local canonical form. Telemetry, the
public view and the ledger snapshot still never contain it. The executor runs
the same isolated provider as the local room, reports stages and measured bytes
(at most once a second), SHA-256-hashes the verified media and sends `finished`
(retried a bounded number of times) or `failed`. Cancel stops it without a
failure report and removes its files. The room host still performs the single
queue add; pulling the verified file from the worker is the remaining step.

### Verified file transfer (#589)

When a worker's `finished` arrives the host calls `TransferHost.collect(job)`:
it sends a `ticket` message (authenticated RPC), which makes the worker's
`TransferServer` (LAN-only, `GET /acq/<job>/<token>`) offer **only** that
verified file under a fresh random token that expires in 15 minutes and is
revoked on cancel. The host streams it to a private `.part` file (size bound,
time bound, `Range` resume, bounded retries) and publishes it atomically only
when both the byte count and SHA-256 equal the executor's report. Then, and
only then, `AssignmentLedger.enqueue_once` admits one queue add and the verified
local copy is delivered. Wrong token, unknown job, expiry, swapped file,
oversize stream and non-LAN endpoints all fail closed; a failed transfer leaves
nothing queued and can be retried. A worker never sends a path, URL or address.

### Using mesh workers from the room (#589, opt-in)

Two settings in `config.json`, both **off by default**: `mesh_remote_acquisition`
(this room may hand link downloads to trusted mesh workers) and
`mesh_accept_acquisition` (this node will run downloads for the room host; read
live, so turning it off makes the node answer `declined`). `src/cast_mesh.py`
builds `mesh_acquisition_app.RemoteAcquisition` only when either is on. For the
room host it wraps the local provider in a `CompositeProvider`: a local worker
is used when this host has one for the kind, otherwise a live peer that
advertises `acquisition-assign-v1` plus `acquire-<kind>-local`. `LinkJobs` is
unchanged and keeps the journal, guest status and the one queue add; the remote
path just returns a verified local file. A lost, restarted or unreachable worker
makes the job fail as *ambiguous* and is never reassigned; after a restart
`reconcile()` asks workers to stop and resolves a job only on an acknowledged
stop. A damaged ledger disables remote use rather than guessing. Free space and
slots of a worker are enforced by that worker (it refuses when full); they are
not advertised. This is trusted-LAN, not cryptographic.

Limitation: the room only creates `LinkJobs` when this host has a local worker
(or the portal is changed to also create it when `mesh_remote_acquisition` is
on), so a host with no local tools cannot yet submit remotely.
