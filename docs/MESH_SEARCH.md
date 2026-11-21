# Mesh library sharing and search — design

Status: **design** (21 Nov 2026). Direction comes from [VISION.md](VISION.md);
mesh membership and transport come from [MESH_DESIGN.md](MESH_DESIGN.md). Builds
on the existing local index ([LIBRARY_INDEX.md](LIBRARY_INDEX.md),
`src/library_index.py`) and tickets #349 (shared music library), #366 (content
fingerprints), #367 (house catalogue) and #387 (protocol versioning). Where a
ticket's acceptance criteria are stricter, they win; update both.

## What we want

1. Every media node has a **media library** — one or more folders chosen in
   Preferences — that it indexes locally and **shares to the mesh**.
2. Anyone in the house — on a node, a phone or an iPad — can **find** a film,
   episode, song, album or artist in **any** node's shared library, instantly,
   and play it in a room, add it to the shared queue, or download it.
3. Search stays **fast and available** when nodes are slow, asleep or gone:
   nodes that have seen each other before keep a **replica** of each other's
   shared index, with a **TTL**, and keep it current.
4. **Shared-nothing**: no central server, no shared database, no single point
   of failure. Each node owns its own library and answers for it; everyone
   else only caches.

## Vocabulary

| Term | Meaning |
| --- | --- |
| **Origin** | the node that holds the files and owns the index entries for them |
| **Shared folder** | a library folder the origin's owner has marked *Share with the house* |
| **Entry** | one indexed media item: content_key + metadata + relative location |
| **Replica** | a peer's read-only cached copy of an origin's shared entries |
| **Generation** | `(origin_id, epoch, seq)` — epoch changes on reindex/reset, seq increments per change |
| **Soft TTL** | age after which a replica is revalidated when the origin is reachable |
| **Hard TTL** | age after which a replica of an unseen origin is deleted |

## Architecture

```
                 ┌──────────── each node (shared nothing) ─────────────┐
 Preferences ──► │ Library folders ─► Indexer ─► local.sqlite3          │
  (folders,      │  (watcher +        (tags,     ├ entries (owned)      │
   share toggle) │   periodic         ffprobe,   ├ changelog (seq)      │
                 │   rescan)          fingerprint)└ fts5 + trigram       │
                 │                                                       │
                 │ Replicator ◄──── mesh gossip: origin advertises        │
                 │  pull deltas      (epoch, seq) in its heartbeat        │
                 │  since seq ─────► replicas.sqlite3 (per-origin rows)   │
                 │                                                       │
 Web / desktop ─►│ Search API ─► query local + replicas (no network)      │
  "Find"         │              └► optional fan-out to stale origins      │
                 └───────────────────────────────────────────────────────┘
```

Search never *needs* the network: it reads the local index plus replicas. The
network keeps replicas fresh and fills gaps.

## 1. Choosing and indexing the library

**Preferences → Library** (desktop node):

- A list of folders, each with a label ("Films", "Kids", "Music", "Holiday
  videos"), a **Share with the house** switch (on by default for new folders),
  a kind hint (Auto / Films & TV / Music / Photos & home video) and live status
  ("Indexed 4,812 items · 2 min ago", "Scanning… 61%", "Folder missing").
- Add with a folder chooser; remove asks whether to forget the index entries.
- No automatic home-drive scan, ever: only chosen folders are indexed.

**Indexer** (GTK-free, off the main thread, `nice`d, bounded):

- Extends `library_index.py` from video-only to video **and audio**, with
  bounded tag metadata: title, year, show/season/episode (#368 parser), artist,
  album artist, album, disc/track, genre, duration, resolution, audio/subtitle
  languages, rating, has-lyrics, has-artwork.
- Metadata sources in order: embedded tags (via bounded, network-disabled
  `ffprobe`), sidecar NFO/LRC, then filename/folder parsing. Never the internet.
- Identity: the **quick content fingerprint** from #366 (`content_key`) is what
  leaves the node. The existing full SHA-256 stays local and optional.
- **Change detection**: OS file watcher where available (inotify, FSEvents,
  ReadDirectoryChangesW — optional dependency, lazily imported) with a 2 s
  debounce; always backed by a periodic incremental rescan (default every
  15 minutes, stat-based, cheap) because watchers drop events on network
  shares, sleep and overflow.
- Every add/update/remove writes the entry **and** appends to a changelog with
  the next `seq` in one SQLite transaction.
- Hard limits (defaults): 200,000 entries per node, 32 shared folders, 64 KiB
  per entry. Hitting a limit is reported in the UI and never deletes data.

**Local schema** (sketch):

```sql
entries(content_key PRIMARY KEY, folder_id, rel_path, kind, title, sort_title,
        year, show, season, episode, artist, album_artist, album, disc, track,
        genre, duration, width, height, langs, rating, size, mtime, updated_seq)
changelog(seq INTEGER PRIMARY KEY, content_key, op /* upsert|delete */)
entries_fts USING fts5(title, show, artist, album, album_artist, genre,
                       tokenize="unicode61 remove_diacritics 2")
entries_tri USING fts5(sort_title, tokenize="trigram")   -- substring & typo tolerance
meta(origin_id, epoch, seq, schema)
```

`rel_path` is relative to the shared folder and shown only as the folder label
plus relative path ("Films / Paddington 2 (2017).mkv"). Absolute paths never
leave the node.

## 2. Sharing: replication between nodes that know each other

**Advertising.** Every mesh heartbeat (MESH_DESIGN M4) carries the origin's
library generation `(epoch, seq, entry_count)` and its search capability
(`search.v1`, negotiated per #387). That costs a few bytes.

**Pulling.** A node whose replica of origin O is behind asks O, over the mesh
HTTP channel:

- `GET /mesh/library/changes?epoch=E&since=S&limit=5000` → ordered upserts and
  deletes after `S`, with `next`; or **410 Gone** if `E` is stale or `S` is
  older than O's compacted changelog.
- On 410 (or first contact): `GET /mesh/library/snapshot?page=…` — paginated,
  gzip-compressed JSON lines of all shared entries at a stated generation, then
  continue with `changes` from that generation.

Properties:

- **Idempotent and order-safe.** Applying the same page twice, or a snapshot
  then overlapping changes, yields the same replica. Each origin writes only its
  own rows, so there are no conflicts to resolve.
- **Compaction.** Origins keep at least 7 days or 100,000 changelog rows,
  whichever is larger; older peers fall back to a snapshot.
- **Backpressure.** One replication stream per origin at a time; pages are
  applied in a single transaction; at most 2 concurrent snapshot pulls per node;
  bandwidth capped (default 2 MB/s) and paused while that node is transcoding
  for playback.
- **Unsharing.** Turning off *Share* on a folder emits deletes for its entries,
  so replicas drop them within one sync (seconds when the origin is online).

**Replica storage.** One `replicas.sqlite3` per node with an `origin_id` column
on every row, its own FTS tables, and per-origin bookkeeping:

```sql
origins(origin_id PRIMARY KEY, name, epoch, seq, entry_count,
        last_synced_at, last_seen_at, state /* fresh|stale|offline|evicting */)
```

## 3. TTL and freshness

| Rule | Default | Behaviour |
| --- | --- | --- |
| **Live** | origin heartbeating | replica pulled within 2 s of any advertised change |
| **Soft TTL** | 10 min since last sync | on next search or heartbeat, revalidate (`changes since seq`; usually empty) |
| **Offline** | origin not seen > 30 s | results still shown, marked *offline · last seen 14:02*, sorted below online copies |
| **Hard TTL** | origin not seen for 7 days | replica rows deleted; origin forgotten until it reappears |
| **Epoch change** | origin reinstalled/reset | replica discarded, fresh snapshot |
| **Corrupt replica** | integrity check fails | drop that origin's rows, resync; never crash |

TTLs use a node's own receive times, so clock skew between PCs doesn't matter.
"Nodes that have seen each other before" is simply origins still in the replica
store: when the Bedroom laptop wakes up after a weekend away, its peers already
hold its index and only fetch the few changes since.

## 4. Searching

**Query path (per keystroke, debounced 120 ms):**

1. Normalise: NFKC, casefold, strip diacritics; split tokens; recognise simple
   filters (`kind:music`, `on:study`, `year:1990s`, `artist:abba`).
2. Run FTS5 `MATCH` (prefix on last token) against local + replica tables, with
   BM25 weights title > show/artist/album > genre. If there are fewer than 5
   hits, add trigram matches for substring and typo tolerance ("padingtn" →
   Paddington).
3. **Merge copies**: group by `content_key`, then by shared embedded IDs; one
   result lists every copy and its availability.
4. **Rank**: BM25, then boosts for exact or prefix title match, online origin,
   origin near the chosen room, items the searcher started recently (#365), and
   kind matching the current context (e.g. music while the room is in a music
   session).
5. **Optional live fan-out**: for origins that are online but have no replica
   yet, or are past the soft TTL, send the query to them in parallel
   (`GET /mesh/library/search?q=…`, 300 ms deadline). Their hits stream into the
   results as they arrive (SSE), and kick off a background replica sync.

**Search API** (web clients and the desktop share it):

- `GET /api/search?q=&kind=&origin=&limit=50&cursor=` → grouped results
  (Films, Shows, Artists, Albums, Songs, Other) with opaque IDs, copies,
  availability and `partial: true` while fan-out is still running.
- `GET /api/search/stream?q=` (SSE) → `results`, `more`, `done` events for
  incremental UI.
- `GET /api/libraries` → nodes and their shared folders (label, kind, counts,
  state) for browsing.
- `GET /api/libraries/<origin>/<folder>?path=` → paginated folder browse
  (relative paths only).

## 5. The "Find" section (web and desktop)

- One search box at the top of the remote ("Search the house"). Results appear
  as you type, grouped by type, with large touch targets.
- Filter chips: **Films · Shows · Music · Home videos**, plus one chip per node
  or person ("Study PC", "Dad's laptop") and **Available now**.
- Each result shows the title, year or artist, duration, where it lives
  ("On Study PC · also on Lounge PC"), and availability ("Asleep — wake it?"
  with #4 wake-on-demand from VISION).
- Actions: **Play in…** (room picker), **Add to Up Next**, **Play next**,
  **Download** (#369), **More from this album/show/artist**, and **Show in
  library** (opens the folder browse).
- **Libraries on the network**: browse each node's shared folders as a simple
  tree, or by Artists, Albums and Shows; sort A–Z, recently added, or year.
- Empty and edge states with exact copy: "Nothing in the house matches
  “padingtn”. Did you mean **Paddington**?"; "Dad's laptop is offline —
  showing what it had at 14:02."; "Still checking 1 computer…".

## 6. Playing what you found

Results carry a `content_key` and the origin of each copy. Playing goes through
routing (#355), the mesh range proxy (VISION pillar 3) and transcode offload
(#388). Immediately before play, the origin **revalidates** the entry (file
exists, fingerprint unchanged, still in a shared folder); otherwise the result
is marked gone and the next copy is tried.

## Trust and safety (trusted home LAN)

Per the VISION trust model, any device on the LAN may search all shared
folders. What we still enforce, as correctness rather than distrust:

- Only **shared** folders are indexed for the mesh; unshared folders stay local.
- No absolute paths, usernames or home directories in any payload.
- Host/Origin checks on the HTTP API (protection from hostile web pages).
- Size limits and schema validation on every replication page and query (fuzz
  tested); a misbehaving origin can't bloat or crash its peers.

## Performance budgets (asserted in CI with synthetic libraries)

| Metric | Budget |
| --- | --- |
| Local + replica query, 100k entries per origin × 3 origins | ≤ 30 ms p95 |
| Keystroke → results on a phone over the LAN | ≤ 100 ms p95 (cached) |
| Fan-out to a stale origin | ≤ 300 ms deadline, never blocks cached results |
| Initial replica of a 100k-entry origin | ≤ 10 s, ≤ 15 MB transferred |
| Change on origin → visible in peers' search | ≤ 3 s online (watcher), ≤ 15 min worst case (rescan) |
| Idle replication traffic | ≈ 0 (generation piggybacks on heartbeats) |
| Replica storage | ≤ 150 MB per 100k entries per origin, enforced |

## Testing strategy

- Pure tests for normalisation, query parsing, ranking and copy merging.
- Property tests: replicas converge to the origin's state for any interleaving
  of snapshots, change pages, duplicates and restarts (seeded, 100+ seeds).
- Deterministic multi-node simulator with a fake clock: TTL expiry, offline
  marking, epoch reset, compaction → snapshot fallback, unshare propagation.
- Fuzzing of replication pages and search queries (oversized, malformed,
  hostile Unicode).
- Benchmarks on generated 100k-entry libraries, gated in CI (#206).
- No GTK, no real network: loopback HTTP and in-memory SQLite only.

## Delivery slices (proposed tickets)

| Slice | Scope | Depends on |
| --- | --- | --- |
| S1 | Preferences → Library folders (label, share switch, kind, status) | — |
| S2 | Indexer v2: audio + tags + watcher + periodic rescan + changelog | #366, #349 |
| S3 | FTS5 + trigram local search, query parser, ranking, `/api/search` | S2 |
| S4 | Replication protocol: generation in heartbeat, changes/snapshot, compaction | S2, #387, #352 |
| S5 | Replica store, TTL/state machine, corruption recovery | S4 |
| S6 | Federated query: replica merge + live fan-out + SSE streaming | S3, S5 |
| S7 | "Find" UI on web remote and desktop; libraries browser | S3, S6 |
| S8 | Play-from-result revalidation and copy failover | S6, #355 |
| S9 | Benchmarks and simulator gates in CI | S3–S6, #206 |

#349 becomes the music-facing part of S2/S3/S7; #367 becomes S4–S6.
