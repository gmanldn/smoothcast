# Peer protocol evolution — compatibility contract (#387)

SmoothCast nodes may run different application releases. This document governs
the **feature handshake** used by the mesh, not the existing v1 record wire
format. The runtime authority is src/peer_protocol.py; mesh replication uses it
in src/mesh_sync.py. These rules complement the trusted-LAN trust model in
docs/VISION.md. The handshake does not authenticate a peer or grant media access.

## Handshake (additive to existing v1 sync/push RPC)

Each request and reply carries a small hello object:

```json
{"proto":1,"min_proto":1,"app_version":"1.2.15","caps":["mesh.records.v1"]}
```

* proto: maximum integer protocol understood. min_proto: oldest accepted.
  Both are positive, no more than 65535, and min_proto <= proto.
* app_version: three decimal components; information only, never used for
  deciding whether an operation is supported.
* caps: a set of at most 32 unique capability names. A capability is enabled
  **only when both peers explicitly advertise it** and the local peer kill
  switch has not disabled it. Unknown caps do nothing.
* The hello must be a JSON object of at most 4096 encoded bytes. Unsupported
  ranges, malformed required fields, duplicate caps and oversized messages
  are refused before state exchange. Future optional fields are ignored.
* Protocol overlap is [max(min_proto), min(proto)]; select its largest integer.
  Empty overlap returns incompatible_protocol with no digest or records.
* For old v1 nodes that omit hello, assume proto 1 and an **empty** cap set.
  Keep base record sync working. Do not infer any opt-in feature from an
  older application version, a NodeRecord capability, or missing handshake.
* Outbound sync/push replies are checked **before** applying any peer records.
  Never accept a response carrying an error or malformed/incompatible hello.
  Failed exchanges back off; they cannot alter the queue or receiver session.

The compatible base record exchange remains v1. The capability
mesh.records.v1 advertises that baseline; subsequent mesh features must use
new names such as resume.v1 and separately guard every read/write with the
negotiated agreement. For diagnostics, count compatibility refusals without
logging private paths, tokens or IP addresses.

## Protocol versus data schema

A protocol version change is required for breaking envelope/transport changes.
An additive optional field does **not** require a bump. A new capability
requires the feature to work correctly when the other side lacks it.

Version all newly synced persistent documents with integer schema. Use
peer_protocol.parse_store before editing: its lossless JSON copy preserves
unknown fields and forbids writes when the stored schema exceeds the reader's
supported schema. A downgrade may display supported information but must not
write a document whose newer fields it cannot preserve semantically.

**NodeRecord and unknown fields:** `NodeRecord` relays additive *top-level*
fields from newer nodes losslessly in `NodeRecord.extra` (sorted `(key,
canonical JSON)` pairs). They are bounded (16 fields, 4 KiB total, depth 4,
integers only, lowercase `[a-z][a-z0-9_]{0,31}` keys), never shadow a known
key, never reach the public or guest tiers, and are dropped first if they would
push a record over `MAX_RECORD_BYTES`. Out-of-bounds extras are skipped, not
fatal. Unknown fields *inside* nested items (targets, clients, sources,
edges) are relayed the same way in each item's own `extra` (4 fields, 256 bytes
per item, same key/value rules), never exposed in the guest tier, and dropped
before any known data when a record must shrink. Migrate each persistent shared
store to the lossless document wrapper before enabling its sync capability.
`peer_status_text()` holds the user-facing copy for older or incompatible peers;
a Network/health row should render it (not yet wired into `mesh_ui.py`).

## Rollout and testing

1. Deploy handshake support first while the peer record format remains v1.
2. Exercise golden messages in tests/test_peer_protocol.py, including legacy
   omissions, malformed and oversized handshakes, unknown fields, the full
   capability intersection matrix, and downgrade read-only behaviour.
3. Exercise actual sync/push boundaries with the deterministic mesh simulator
   in tests/test_mesh_protocol.py. Incompatible hello must never change state;
   legacy v1 must still exchange base records.
4. Roll out a new cap only after both sender and receiver gate it. Keep the
   per-peer disabled_caps_by_peer switch available for emergency rollback.
5. During a single minor-version transition, keep the previous protocol
   supported where safely possible. Never silently delete fields or execute a
   new feature on a node that did not explicitly advertise it.
6. Real Windows/macOS/native device qualifications remain in #208/#209.
