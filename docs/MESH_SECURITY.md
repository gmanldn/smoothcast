# Mesh security and abuse resistance

Scope: the mesh layers in `src/mesh_*.py` (docs/MESH_DESIGN.md). Trust model:
the **trusted home LAN** (docs/VISION.md). Nodes on the LAN join automatically;
this page lists what is still defended, because it is engineering correctness
and invisible to residents, and what is deliberately *not*.

## Attackers considered

| Attacker | Example |
| --- | --- |
| Buggy or hostile device on the LAN | sends garbage, floods datagrams/requests, replays old packets |
| Misconfigured clone | copied config gives two machines one `node_id` |
| Hostile web page in a guest's browser | cannot reach the mesh: no browser-reachable mesh listener; the guest feed requires the room session and Host check |
| Out of scope | a hostile resident, a shared office/dorm network, the internet |

## Defences (and tests, `tests/test_mesh_security.py` unless noted)

- **Bounded input.** Datagrams <= 512 B, records <= 16 KiB, RPC bodies <= 128 KiB;
  strict parsers raise one error type (`tests/test_mesh_model.py`, `test_mesh_beacon.py`
  fuzzing). Control characters, URLs-as-names and unknown enums are rejected.
- **Rate limits.** Per-source token buckets on beacons and RPC; bucket tables,
  peer table (64), member table, tombstones, dead-boot memory and caches are all
  capped. A 60 s flood leaves tables bounded and legitimate peers intact.
- **Sybil resistance.** When a table is full the *newest* unknown identity is
  refused; established peers are never evicted.
- **No endpoint hijack.** A node still beating from its address cannot be displaced
  by another source claiming its identity (`address_conflicts`); a real move is
  accepted once the old address is silent for 1.6 s.
- **Replay.** `WELCOME` must echo a recent nonce we sent; `(boot_id, rev)` and
  incarnation only move forward; dead boots are refused for 60 s; a departed boot
  cannot return from a late datagram.
- **Forged goodbyes.** Honoured only for the known boot from its known address, and
  then confirmed by a direct probe before removal.
- **Clones.** Detected and reported; the later-started process gives up the id.
- **Revocation.** `Replicator.revoke(node_id)` removes the peer from the view,
  ignores its presence, and refuses its sync/push calls until `unblock`.
- **Authorisation.** Protected calls (`sync`, `push`) require a private-LAN source
  that is not revoked; optional `strict` mode (`MeshPolicy`) also requires the
  caller to be a current member. `ping` stays public.
- **Audience tiers.** Public, guest and full serialisers have fixed allow-lists
  (`mesh_model`); guest payloads never contain other nodes' client names,
  addresses, edges or shared-media summaries (`tests/test_mesh_clients.py`).
- **No side effects on playback.** Mesh modules import no playback, casting or
  general network-client code (static test); observation only reads discovery
  results and opens bare TCP connections (`tests/test_mesh_visibility.py`).

## Residual risks (accepted)

- Identity is **recognition, not authentication**: on an open LAN any device can
  claim an unused `node_id`, or a node's identity while it is silent. Pinned
  certificates (#358, `mesh_transport.py`) remain optional hardening.
- Presence and sync are plaintext on the LAN (like the room itself, #340).
- A hostile LAN member can still waste a node's bounded CPU; limits keep it bounded,
  not zero.
