# SmoothCast vision — one house, one mesh, one queue

Status: **authoritative product direction** (adopted 21 Nov 2026). Where an
older document, ticket or design disagrees with this page — especially on
security and trust — this page wins; reconcile the other document when you
next touch it. Implementation detail still lives in tickets and design docs
such as [MESH_DESIGN.md](MESH_DESIGN.md).

**Order of work is set separately.** This page is the destination. The sequence,
the deferred (icebox) items and the rules for agents live in the strategy epic
[#511](https://github.com/gmanldn/smoothcast/issues/511); where the two differ
on *what to build next*, #511 wins. In short: quality and foundations first,
then power-user features, then the household features marked below as deferred.

## The goal

SmoothCast is a **lightweight, universally available and responsive smart mesh**
of media nodes, web clients and casting targets that work together, ebbing and
flowing, to manage a household's media — whoever lives there, whatever
equipment they own, and whoever drops round for the evening.

- **We control the mesh as one.** There is no "which computer is it on?". Any
  node, any phone, any tablet shows the same house, the same library and the
  same queue, and can drive any room.
- **Files are streamed around.** Media stays where it is stored and flows to
  wherever it is played. Moving bytes is the mesh's job, not the resident's.
- **We share a queue.** One shared Up Next that everyone present can add to,
  reorder and play from, from any device.
- **Slicker and more open than what exists.** No accounts, no cloud, no
  subscription, no app install for anyone but the person who runs a node. An
  open, documented protocol and plain-file data you can read, script and leave.
- **Quality of engineering first.** Before we add a feature we make sure it is
  deterministic, bounded, tested without hardware, and explains itself when it
  fails.
- **Elegant before big.** The mantras are *universal, simple, fast, compatible*.
  Linux, macOS and Windows are equally first-class. SmoothCast never crashes:
  every failure reaches the user as a sensible, polite message. When a feature
  would add complication without a clear payoff, we defer it rather than ship
  it half-built.

## The house we design for

A concrete reference household. Every feature should make sense here.

| Thing | Example | Role in the mesh |
| --- | --- | --- |
| **Study PC** (Linux, GPU, big disk) | most films and the music library | media node, strongest transcoder |
| **Lounge PC** (Windows, HDMI to the TV) | some films, plugged into the main TV and soundbar | media node, primary screen |
| **Bedroom PC** (macOS laptop) | holiday videos, a few downloads; often asleep | media node that comes and goes |
| Chromecast / Google TV, DLNA TV, smart speakers | lounge, kitchen, kids' room, garden | casting targets |
| Residents' phones (Android, iPhone) | 4 people | remotes, uploaders, private speakers |
| iPads | 2 | remotes and screens (a kitchen iPad on a stand) |
| Guests | 0–15 on a Saturday night | remotes and contributors, from their own phones |

The three PCs form **one mesh**. Any of them may be off, asleep, updating or on
an older version; the house keeps working with whatever is awake.

## Trust model: the trusted home LAN

**Decision.** SmoothCast assumes that everyone on the local network has been
given the Wi-Fi password and is not a malicious actor. Being on the LAN *is*
the invitation. We do **not** build login walls, PINs, pairing ceremonies,
per-guest permissions or encryption to defend the house against the people in
it.

What this means in practice:

- **Joining is instant.** Open `http://smoothcast.local` (or any node's address,
  or scan the QR on the TV) and you are in. You are asked for a display name
  once; the browser remembers it.
- **Nodes find and join each other automatically.** Discovery *is* membership.
  No approval step between the house's own computers.
- **Everyone can drive everything.** Queue, transport, rooms and volume are
  open to every participant. "Roles" exist only as *courtesy* (kids profiles,
  quiet hours, private bedroom speakers) and *tidiness* (guest uploads expire),
  never as security boundaries.
- **Identity is recognition, not authentication.** A per-browser random ID lets
  the mesh remember "this is Sam's phone" for resume points and preferences. It
  is not a credential and nothing depends on it being secret.

What we still do — **because they are engineering correctness, not distrust of
residents**, and because each one is invisible to users:

1. **Never reachable from outside the home.** Bind only to private, link-local
   and loopback interfaces; refuse requests whose source is a public address;
   never open router ports (no UPnP port mapping). The trust model is "the LAN",
   so the LAN must be the boundary.
2. **Defend against hostile web pages, not hostile people.** A guest's browser
   may have a malicious website open in another tab. Such a page can make the
   browser send requests to LAN services (CSRF) or trick DNS into pointing at
   them (DNS rebinding). Keep the cheap, invisible checks: validate `Host` and
   `Origin` against the mesh's own names/addresses and require a JSON content
   type for mutations. This costs residents nothing and stops the internet from
   driving your TV.
3. **Only serve media, never the filesystem.** Paths are resolved inside the
   configured library roots and upload folders, with symlink/`..` containment.
   This is about bugs and accidents (a typo serving `/etc`, a misconfigured
   root), not about distrusting a flatmate.
4. **Bounded everything.** Upload sizes, sessions, connections, transcodes and
   event queues stay capped so one confused phone cannot exhaust a node.
5. **Validate inputs.** Malformed requests get clear 4xx errors, never crashes
   or undefined state. Fuzz tests stay.

Out of scope by design: hostile LAN members, shared office or dorm networks,
internet exposure, multi-tenant use. If you need those, put SmoothCast on its
own VLAN or don't run it there; we say so in the UI and in
[SECURITY.md](../SECURITY.md).

### Consequences for existing work

The following were designed for an untrusted LAN and should be **re-scoped**
when next worked on (keep the engineering — bounds, idempotency, fencing,
revocation-as-tidiness — and drop the gatekeeping):

| Item | Re-scope to |
| --- | --- |
| Room PIN, login lockout, CSRF tokens (`src/portal.py`) | optional "house PIN" setting, **off by default**; keep Host/Origin checks |
| #358 explicit node pairing and trust tiers; MESH_DESIGN "Security tiers" | automatic membership for nodes on the LAN; keep pinned identity only to detect *duplicate/confused* nodes |
| #340 trusted HTTPS for the portal | only where browsers require a secure context (service worker, wake lock, Media Session on some platforms) |
| #315 revoke/rotate, #374 guest passes | tidiness tools: "sign everyone out", guest uploads and names expire |
| #314 / #322 roles and permission panels | courtesy profiles (#363, #364, #376, #375) instead of permissions |

## Design principles

1. **One house, many doors.** Every node serves the same UI and the same state.
   The entry name `smoothcast.local` is held by whichever node is primary and
   moves automatically when it sleeps.
2. **Media flows to where it plays.** The node nearest the target (or the
   fastest transcoder) does the work; the file's home node streams bytes to it.
   Residents never copy files to make playback possible.
3. **Ebb and flow, never break.** Nodes sleep, wake, update and leave. Each
   departure is a *handoff*, not a failure: work drains or migrates, and what is
   playing keeps playing.
4. **Local-first, partition-tolerant.** If the Wi-Fi splits the house in two,
   both halves keep working and merge cleanly when they meet again.
5. **The phone is the remote; any screen is a screen.** No installs. Modern web
   platform features (PWA, Media Session, Wake Lock, Web Share Target, MSE)
   make the browser feel native.
6. **Instant or honest.** Actions confirm in under 150 ms on the LAN, or say
   exactly what is happening ("Waking the Study PC… 4 s").
7. **Open by default.** Documented HTTP/SSE API and mesh protocol, plain JSON
   state files, M3U/XSPF export, importers from other platforms. No lock-in.
8. **Quality first.** Deterministic simulators for the mesh and sync,
   fake receivers, chaos tests, and performance budgets enforced in CI.

## A day in the life

**07:00.** Sam's alarm fades in BBC Radio 4 on the kids'-room speaker (#385,
#380). The Bedroom PC is asleep; the Study PC serves the stream.

**07:40.** Mum taps **Move to kitchen** on her phone. The radio continues on the
kitchen speaker at the same second and stops upstairs (#372).

**12:30.** Dad's laptop wakes from sleep. Within a second it reappears in the
mesh, its holiday videos are back in the house library, and a stale "offline"
badge clears (#367, #386).

**17:00.** Alex downloads the next three episodes of a show to their iPhone for
football practice. On the drive home the phone reports progress back the moment
it sees the house Wi-Fi (#369, #365).

**19:30.** Kids'-room quiet hours start: volume caps at 20% and new films are
blocked on Sam's profile; the audiobook already playing finishes (#375, #364).

**20:00.** Saturday night. Twelve guests arrive. They join the Wi-Fi, scan the
QR on the lounge TV and are in the room with their name — no PIN, no app. They
share songs from their phones straight into the shared queue (#382), vote, and
watch the queue fill. The Study PC transcodes a FLAC album the soundbar can't
decode while the Lounge PC plays it (#388). Someone's video from their phone
plays on the TV **without uploading the whole file first** (stream-from-device,
below).

**22:30.** Movie vote: four candidates nobody present has seen; the winner
starts on the lounge TV after a 5-second countdown (#392). Two guests in the
kitchen watch along on the iPad, in sync, with their own subtitles (#373).

**23:15.** The Bedroom PC lid closes mid-stream. It had announced "going to
sleep" first; the Study PC, which also has that film, takes over at the same
second (graceful drain, below). Nobody notices.

**01:00.** Last guest leaves. Guest names, uploads and votes expire on their
own; the house is tidy in the morning.

## Feature pillars

Existing tickets are linked. Items with a bold issue number came from this vision and are tracked under
epic #436 (trust-model changes: #416, #417, #418). Each new item is scoped so it can be built and tested headlessly.

### 1. Zero-friction access

- **#416 — Open join.** Default room access needs no PIN: display name only,
  remembered per browser. Optional house PIN for people who want it.
- **#419 — `smoothcast.local` that always works.** The primary node advertises
  `smoothcast.local` and an `_smoothcast._tcp` mDNS service; on primary loss the
  next node claims the name within 3 s. Every node also answers on its own
  address and redirects to the same UI. Fallback page lists live nodes when mDNS
  is blocked (some Android/iOS setups).
- **#420 — TV-side QR everywhere.** Every screen (Cast idle slate, `/screen`
  page, desktop) shows a join QR and the short address.
- Residents vs guests as recognition and courtesy (#363), kids (#364).

### 2. One mesh, controlled as one

- Live membership, failure detection and primary succession (#352, MESH_DESIGN).
- Mixed-version compatibility via protocol versions and capabilities (#387).
- One house library across all nodes (#367) with content fingerprints (#366);
  shared-nothing replicated search is designed in [MESH_SEARCH.md](MESH_SEARCH.md).
- Rooms instead of device names (#370), group presets (#371, deferred: rooms are independent, with no cross-room sync promise), private rooms
  (#376), quiet hours (#375).
- House health at a glance (#386).
- **#421 — Partition healing.** The shared queue and room state become
  op-based, mergeable records (sequence CRDT for Up Next, last-writer-wins
  registers for settings) so a split house merges without lost edits. Today's
  revision fencing stays for live transport commands.

### 3. Media flows to where it plays

- Route playback to the best node and copy (#355, #356); transcode offload to
  the strongest node (#388).
- **#422 — Mesh range proxy.** Any node can serve any house file by streaming
  HTTP Range bytes from its home node, so a target only ever talks to one
  nearby node. Bounded buffers, backpressure, resumable on node hiccups.
- **#423 — Predictive warm-up.** When an item becomes "next", the playing node
  pre-probes it, pre-reads the first segments from its home node and, if a
  transcode is needed, encodes the first 10 s in advance. Goal: next item starts
  in under 1 s. Builds on the existing queue pre-warm.
- **#424 — Smart cache.** Each node keeps an LRU cache (configurable disk budget)
  of recently and soon-to-be played items from other nodes, so a sleepy laptop's
  film survives the laptop closing.
- **#425 — Stream-from-device.** A guest's phone can play a local video on the TV
  without a full upload: the browser streams the file progressively to the node
  (chunked upload consumed as it arrives, or WebRTC data channel where
  available) and playback starts after the first few seconds. Falls back to the
  resumable upload (#345).

### 4. Ebb and flow (nodes come and go)

- **#426 — Graceful drain.** On sleep, shutdown or update, a node announces
  "leaving in N s", hands its active streams to another node that has (or can
  proxy) the same file at the same source time, then exits. Uses OS sleep
  inhibitors (logind, macOS power assertions, Windows `SetThreadExecutionState`)
  only for the seconds it needs.
- **#427 — Wake on demand.** Asking for a film that only exists on a sleeping
  node sends Wake-on-LAN (if the node registered its MAC and opted in) and shows
  "Waking the Bedroom PC…" with a live countdown.
- **#428 — Energy-aware choices.** Prefer nodes that are already awake and idle;
  don't wake the gaming PC to transcode something the Study PC can handle.
- Safe updates without interrupting playback (#138).

### 5. The shared queue, done properly

- Everyone edits Up Next, atomically and idempotently (done: #314, #323).
- **#429 — Room follows the house, or goes solo.** One house queue by default;
  any room can "go solo" with its own queue and later rejoin.
- **Conflicts are settled by "last action wins, visibly":** the activity
  timeline (#332) shows who did what. Votes, fair turns and control leases
  (#326, #327, #331) are deferred courtesy features; undo (#328) is Wave 2.
- Movie-night vote (#392), house radio when the queue runs dry (#379).

### 6. Phones and tablets feel native, without an app

- Installable PWA (#341) and share target (#382).
- **#430 — Media Session integration.** Lock-screen and headphone controls,
  hardware volume keys and artwork on phones driving the house.
- **#431 — Screen Wake Lock** for iPads and phones used as screens or remotes on a
  stand; **Picture-in-Picture** for watch-along on a phone.
- Watch together across personal screens (#373), private listening on a phone
  as a speaker (existing screens).
- Offline downloads (#369), photo slideshows (#381), lyrics (#378).

### 7. Everyday intelligence (local only)

- Per-person Continue Watching (#365), series and next episode (#368), intro
  skip (#377), accessibility that follows the person (#389), night mode (#390).
- **#432 — Who's home.** Opt-in presence from residents' phones that have the
  web remote open recently (no tracking beyond the LAN); powers "suggest for
  who's here", alarms and follow-me defaults.
- **#433 — House memory.** "What did we watch last Friday?" — a shared,
  privacy-mode-aware history (#329) separate from personal history.

### 8. Open and integrable

- **#434 — Published API.** OpenAPI description of the HTTP/SSE API, a stable
  versioned mesh protocol doc, and a CLI (`smoothcast mesh status`, `queue add`)
  over the same API. Third parties can build remotes.
- Home Assistant via MQTT discovery (#383); HDMI-CEC TV wake (#384).
- **#435 — Importers and exporters.** Import watched state and playlists from
  Jellyfin/Plex/Kodi exports; export everything (queue, history, rooms) as plain
  JSON and M3U/XSPF.
- Radio and podcasts (#380), request board (#391).

## Engineering bar

Every feature above ships with:

- **Deterministic tests without hardware.** Fake clocks, fake receivers
  (`fakecast`, DLNA fakes), loopback HTTP, the mesh simulator. No sleeps, no real
  TVs, no real GUI (see AGENTS.md).
- **Bounded resources** with documented overflow behaviour.
- **Plain-language failure states**, using the error taxonomy (#207).
- **Budgets asserted in CI** (#206):

| Metric | Budget |
| --- | --- |
| Control action → acknowledged on the LAN | ≤ 150 ms p95 |
| Tap Play → first frame (direct play / transcode) | ≤ 2 s / ≤ 4 s p95 |
| Next queue item start after warm-up | ≤ 1 s |
| Node joins → visible everywhere | ≤ 1 s typical, ≤ 3 s p99 |
| Node leaves (graceful) → streams handed off | ≤ 3 s, no playback gap > 1 s |
| Web remote first paint on a mid-range phone | ≤ 1 s; JS + CSS ≤ 60 KB gzipped |
| Idle node | < 1% of one core, < 2 KB/s mesh traffic |

- **Lightweight.** Pure Python plus FFmpeg on nodes; no database server, no
  container required; the web client is framework-free and fast on old phones.

## What we will not build

- Cloud accounts, remote access over the internet, or relay servers.
- DRM, piracy automation, or scraping of commercial streaming sites.
- A native mobile app **for now**. The web client must first be good enough
  (budgets above, WCAG 2.2 AA). Native apps may be revisited later if the web
  platform cannot deliver something people need, such as reliable background
  controls.
- Defences against hostile people on the home LAN (see the trust model).
