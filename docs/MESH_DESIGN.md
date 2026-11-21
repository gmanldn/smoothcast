# SmoothCast mesh — design

Status: **design only** (planned in tickets #394–#405, M1–M12, under epic #352). Nothing in
this document is implemented yet except what `src/peer_discovery.py`,
`src/mesh_transport.py` and the room portal already do. Where this page and a
ticket disagree, the ticket's acceptance criteria win; update both.

> **Trust model update (21 Nov 2026).** [VISION.md](VISION.md#trust-model-the-trusted-home-lan)
> adopts a *trusted home LAN*: nodes on the LAN join the mesh automatically and
> web clients need no PIN. Principle 2 and "Security tiers" below predate that
> decision. Keep their bounds, validation and identity pinning (to detect
> duplicate or confused nodes) but treat explicit pairing and PIN tiers as
> optional, off-by-default settings when implementing M1–M12.

## Goal

Every SmoothCast **full node** (the desktop app) continuously knows, within a
second or two, about every other full node, every connected web client and
every Cast/DLNA/browser target that any node can see, plus who can reach what.
The picture evolves live as devices join, leave, sleep or change network, and
it never interrupts playback.

The first node on the network is the **primary media node**. Other nodes may
host their own rooms and media; the primary only provides defaults and
tie-breaking (see below). The mesh has **no single point of failure**: losing
any node, including the primary, never blocks the others.

## Design principles

1. **Leaderless data, deterministic roles.** State is replicated by gossip with
   one writer per record, so there are no conflicts to resolve. The "primary" is
   computed identically by every node from the same membership view; there is no
   election protocol to fail.
2. **Discovery is a hint, pairing is trust.** Beacons and mDNS carry identity and
   capabilities only. Anything sensitive (target lists with names, client
   summaries, media offers) flows only over the pinned, paired transport
   (#358, `mesh_transport.py`).
3. **Observation never acts.** Watching the network may read passive status. It
   never sends commands to a receiver, never changes ownership and never
   restarts a session (#352).
4. **Events first, reconciliation second.** Push on change (coalesced) for speed;
   periodic randomised pull repairs anything lost.
5. **Everything bounded.** Records, peers, targets, events, bytes per second,
   threads and cache rows have hard caps with defined overflow behaviour.
6. **GTK-free and clock-injectable.** The mesh core imports no `gi`, takes a
   clock and a network interface, and is tested in a deterministic simulator.
7. **Measure it.** Convergence, failure-detection and bandwidth budgets are
   asserted in CI (#206).

## Layers

```
 UI (GTK desktop, browser Network panel)             M10
 ───────────────────────────────────────────────────
 MeshView: immutable snapshots + coalesced events    M5/M9
 ───────────────────────────────────────────────────
 Replication: delta-state anti-entropy               M5
 Visibility: targets seen, edges, candidates         M7
 Roles: primary succession                           M6
 ───────────────────────────────────────────────────
 Membership + failure detector (SWIM-style)          M4
 ───────────────────────────────────────────────────
 Presence beacon (UDP multicast) + mDNS + seeds      M3
 Pinned HTTPS sync channel (paired)                  #358
 ───────────────────────────────────────────────────
 Wire model, validation, bounds                      M1
 Cache (SQLite)  M8     Security tiers  M11     Runtime/ops  M12
 Simulator + SLO harness                             M2
```

## Identity

| Field | Meaning |
| --- | --- |
| `node_id` | 128-bit random, persisted. Durable identity. Cloned configs are detected (two live nodes, same id, different `boot_id`) and one regenerates. |
| `boot_id` | Random per process start. Distinguishes a restart from a stale record. |
| `incarnation` | Counter per boot that the node itself raises to refute a false suspicion. |
| `started_at` | Wall-clock start, informational only. Never compared across machines. |
| `rev` | Monotonic revision of the node's own record for this `boot_id`. |

Endpoints (address, port) are **attributes**, not identity: a node can change
interface or IP without becoming a new node.

## Records (single-writer)

Each node owns exactly one `NodeRecord` and is the only writer of it:

- `node`: name, version, protocol versions, capabilities (`room`, `source`,
  `screens`, `receiver`, ...), interfaces summary (count only), room URL.
- `targets_seen[]`: for each Cast/DLNA/browser target this node currently sees:
  stable target id (Cast UUID / DLNA UDN / screen id), kind, friendly name, model,
  format capabilities, state (`ready`, `busy`, `stale`, `unreachable`),
  `last_seen_ms_ago`, optional advisory `owner` (node/room currently using it).
- `clients[]`: aggregate of web clients attached to this node: opaque client id,
  role (`controller`, `screen`, `speaker`), capability flags and connection age.
  Display names are shared only with paired nodes.
- `sources[]`: counts and capability summaries of media this node has *opted in*
  to share. Never paths or titles unless the peer is authorised for them.
- `edges[]`: outgoing reachability measurements (`node` or `target` id, last OK,
  round trip, failure reason). Bounded; oldest dropped.

Every record has hard size limits (default 16 KiB; mesh total 512 KiB) and a
canonical encoding so digests are stable.

## Fast presence

- **Join burst.** On start (and on wake or interface change) a node sends a
  multicast `HELLO` at 0, 100, 300, 700 and 1500 ms, then listens. Nodes that hear
  it reply unicast with `WELCOME` (their digest). Both sides then pull deltas.
  Target: new node visible everywhere in **under 1 s typically, 3 s at p99** on an
  uncongested LAN.
- **Heartbeat.** One jittered multicast beacon per second per node carrying
  `(node_id, boot_id, incarnation, rev, port)`. A beacon whose `rev` is ahead of
  the local copy triggers an immediate pull, so changes propagate in one round
  trip rather than waiting for the periodic repair.
- **Goodbye.** A clean shutdown multicasts `GOODBYE`, removing the node in
  under 500 ms. Crashes and power loss are caught by the failure detector.
- **mDNS and seeds.** The existing DNS-SD record stays as bootstrap and for
  networks that block custom multicast. A user may add a seed address; peers
  also gossip their peer lists, so one reachable node reveals the rest even when
  multicast does not work.

## Membership and failure detection

SWIM-style, tuned for a LAN of at most a few dozen nodes:

- `alive` → `suspect` after 3 missed beats (about 3 s) and a failed unicast
  probe; indirect probes via up to 3 other nodes avoid false positives from one
  bad link.
- `suspect` → `dead` after a further 3 s without refutation. A node refutes by
  raising its `incarnation`.
- `dead` records are kept as tombstones (60 s) so a delayed gossip message cannot
  resurrect them; a higher `boot_id`/`incarnation` does.
- Sleep/wake and large monotonic-clock jumps trigger a join burst and an
  incarnation bump instead of mass suspicion.
- Partitions heal by merging records per owner; no data is lost because each
  record has one writer.

## Replication

Scuttlebutt-style delta state. Digest = `{node_id: (boot_id, rev)}`. Two nodes
exchange digests and send only newer records (or per-section deltas when a
record is large). Pushes are coalesced to 50–100 ms; each node also pulls from
one random peer every 5–10 s to repair losses. Transport: pinned HTTPS for paired
peers; unpaired peers receive only the public identity tier (see Security).

## Primary media node

The primary is `min(started_order)` over `alive` full nodes, where
`started_order = (boot_epoch, node_id)` and `boot_epoch` is each node's own
announced start time. Because only the order of announced values is compared,
clock skew between machines affects only *which* node is first, never
correctness. Hysteresis (a node must be alive for 5 s before it can displace or
be displaced) prevents flapping.

The primary:

- is the default room offered to a guest who opens the mesh entry address;
- names the mesh and breaks ties for advisory fields (`owner` display);
- owns **nothing else**: it does not own other nodes' rooms, queues, receivers or
  media. Handover on loss is automatic and silent; existing rooms continue.

## Target visibility

Each node publishes what it sees; every node derives a **visibility matrix**
(target × node) with freshness. A target seen by several nodes is one entry with
the list of nodes that can reach it. Peer-reported facts are *candidates*: the
route chosen for a play request verifies reachability and capability itself
before any command is sent (#352, #355, #356).

## Web clients

Browsers attach to one node (their room host). That node aggregates its clients
into its record, so every full node sees "who is connected where". Browsers
receive the mesh through the authenticated room event channel (#316): a snapshot
on connect, then versioned deltas, with a full snapshot on any gap. A browser
screen registered with a node is advertised as a target by that node, and
commands are routed through it.

## Persistent cache

A bounded SQLite cache stores last-known peers and target metadata so the UI
shows the whole home instantly at start (as *last seen* until confirmed live),
and route decisions have history. Never stored: PINs, cookies, media paths,
titles. TTLs: peers 7 days, targets 30 days. **Forget network** wipes it.

## Security tiers

| Tier | Who | Gets |
| --- | --- | --- |
| Public | any LAN device | node id, protocol version, capability names (as today) |
| Paired node | explicit host approval (#358) | full records, edges, client summaries, scoped media offers |
| Web guest | room PIN | room-scoped snapshot only (their host's view) |

All inputs are size-bounded and rate-limited; unknown versions are ignored;
beacons are never trusted for anything beyond "go and ask over the right tier".

## Budgets (asserted in tests)

| Metric | Budget |
| --- | --- |
| Join → visible on all nodes | ≤ 1 s typical, ≤ 3 s p99 |
| Clean leave → removed | ≤ 500 ms |
| Silent loss → `dead` | ≤ 6–7 s |
| Target appears → visible to nodes and open browsers | ≤ 3 s |
| Steady-state traffic | ≤ 2 KB/s per node at 20 nodes |
| Idle CPU | < 1 % of one core |
| Memory | ≤ 8 MiB mesh state |

## Ticket map

| Id | Ticket |
| --- | --- |
| M1 (#394) | Wire model, validation and bounds |
| M2 (#395) | Deterministic simulator and SLO harness |
| M3 (#396) | Presence beacon and join burst |
| M4 (#397) | Membership and failure detector |
| M5 (#398) | Delta-state replication and MeshView |
| M6 (#399) | Primary media node succession |
| M7 (#400) | Target visibility and reachability edges |
| M8 (#401) | Persistent metadata cache |
| M9 (#402) | Web client presence and live mesh push |
| M10 (#403) | Mesh UI, desktop and browser |
| M11 (#404) | Security tiers and abuse resistance |
| M12 (#405) | Runtime integration, diagnostics and kill switch |

Suggested order: M1 and M2 first (model and simulator), then M3 → M4 → M5, then
M6–M9 in parallel, M11 reviewing each, M10 and M12 last.
