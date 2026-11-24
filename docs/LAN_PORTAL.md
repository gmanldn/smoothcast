# SmoothCast shared room

When the SmoothCast desktop app is running, it starts a small web room on the
selected private LAN IPv4 interface. The **Room** tab of the main window's
side panel shows the address. Open that address in a browser on the same local
network, enter your name, and you join a shared queue with everyone else in the
room. Joining is open by default on the trusted home LAN; an optional **House
PIN** can be enabled in Preferences when people you do not trust use the Wi-Fi.
The app remains the single owner of the queue and the receiver; web actions are
marshalled onto the GTK thread.

Each person can add audio or videos from their device, add uploads to the queue
instead of playing them immediately, vote on titles, reorder or remove entries,
clear Up Next, start a title, skip forward/back, and use play/pause, stop, seek
and volume. Clearing Up Next never stops or replaces the active cast.
Queue moves, removals and clears carry the latest queue revision; if another
client or the desktop changes the order first, the stale edit is rejected and
the dashboard refreshes before the user retries. Edits also use per-participant
command IDs: an identical retry returns its original receipt, while reusing an
ID for a different edit is rejected. Recent receipts are held in a bounded
two-minute cache.
Authenticated remote traffic is bounded independently for each room participant, not by
IP address or a browser-supplied client ID. Defaults are token buckets for
read requests (16-request burst, replenishing 4/second), transport/queue
mutations (12-request burst, 6/second), and upload control/chunks (40-request
burst, 20/second). Exceeding a budget returns HTTP 429 with a `Retry-After`
header; the browser delays polling and retries upload chunks, while
transport actions display a visible refusal rather than continuing to flood.
The control dispatcher also permits at most two concurrent outstanding
commands per participant, so one guest cannot monopolise the shared queue.
Limits do not apply to the host's local desktop controls. The limiter stores
at most 512 recent participant/route buckets and contains no media-path data.

For dependable touch control, the room holds a pressed queue button through
the click event even if a live update reorders Up Next. Rows and action IDs
remain stable across refreshes; outstanding taps show a waiting message and
the latest unsent seek/volume intent supersedes older unsent values. Dragging
the volume slider coalesces changes into at most one request per 150 ms and
commits the final value when released; while a slider is being edited, live
receiver updates do not move its thumb.

The room also shows live presence and a bounded activity feed. An open room
refreshes about every two seconds while visible, backs off if the host stops
responding, and refreshes again when you return to the tab. Votes are a
visible signal and are preserved across refreshes; queue order remains under
the room's control so nobody's film can be silently displaced.

Status responses read a versioned snapshot published by the desktop's GTK
thread, so a busy UI does not make phone polling wait for a UI callback. The
response includes `snapshot_age_ms`; playback and control mutations publish a
fresh snapshot, and progress is refreshed by the normal UI tick.

The **On your network** card in the desktop app and dashboard lists currently
playing, buffering or paused media reported by reachable Cast and DLNA
receivers discovered on the LAN. It refreshes every 15 seconds, shows the
receiver, media title and available progress, and never sends commands to those
other receivers. Unreachable devices are omitted; titles in the dashboard are
visible only after joining the room.

The **Nearby SmoothCast hosts** list uses a separate, versioned DNS-SD record
to show other SmoothCast instances on the LAN. It contains only a random
instance identifier, friendly host name, protocol version and capability names;
it does not contain a PIN, session, user nickname or media path. Opening another
host takes the browser to that host's own join prompt. Discovery alone cannot
transfer a file or issue Cast commands. If multicast discovery is unavailable,
the UI reports that state rather than implying that no peers exist.

The address is a friendly mDNS name such as
`http://smoothcast-lounge.local:PORT/`. SmoothCast derives the name from the
machine hostname, prefixes it with `smoothcast`, and advertises it with
mDNS/Bonjour when the `zeroconf` dependency is available. The card also shows
the numeric IP address as a fallback for networks that block multicast DNS.

Scan the room QR with your phone camera to open the numeric room link,
then enter your name (and the House PIN if enabled). The QR is generated locally
and contains only the address. You can also use **Copy link**.

The portal chooses a port by binding directly to an operating-system-assigned
ephemeral port. It does not check a port and bind later. It uses Python's
standard-library `http.server` module; no web framework, portal package or
additional runtime dependency is installed. The page, styles and scripts are
served locally with no external assets.

## LAN swarm roadmap

SmoothCast is moving toward a live LAN swarm of full instances, paired browser
guests and media targets. Each full instance can host a room and discover nearby
instances, Chromecasts and DLNA renderers. A room has one authoritative shared
queue for music, films and other media. Trusted participants collaborate on that
queue, and a full instance can host its own room while serving as a source or
receiver for another. Browser guests get the same everyday queue and playback
controls where the chosen route supports them.

The source and target pickers should update as devices join, leave or change
capabilities. SmoothCast should choose a reachable, compatible and authorised
route for each play request without disrupting existing playback.

File transfers work in either direction in the planned swarm. A node can offer
to send a copy or ask another node for file access. If the other node approves
the request, the requester can browse the approved media, select files and
transfer copies into its own instance. Transfers should use bounded storage,
show progress, support cancellation and resume after an interruption. Completed
copies should be verified before they become available to the receiving room.

Today the nearby host list opens other rooms and the portal accepts uploads
from the guest's own device. Follow [the swarm roadmap][swarm],
[peer pairing][pairing], and [node-to-node file transfers][transfers] for the
remaining work.

[swarm]: https://github.com/gmanldn/smoothcast/issues/352
[pairing]: https://github.com/gmanldn/smoothcast/issues/358
[transfers]: https://github.com/gmanldn/smoothcast/issues/357

## Screens: browsers as playback targets

Any phone, tablet, laptop or smart-TV browser on the LAN can become a **screen**
(video) or **speaker** (audio) for the room, with nothing to install. Open
`/screen` on the host's address (for example `http://smoothcast-lounge.local:PORT/screen`),
name the device, enter your name (and the House PIN if enabled), and press
**Start screen** once so the browser allows sound. The device then waits for the
room to send it something and keeps itself awake where the browser supports a
screen wake lock.

`GET /join-slate.png` is a public 1920×1080 PNG (room name, join QR and the
numeric `IP:PORT` address, never a PIN) suited to an idle-TV slate; it returns
503 when the QR/imaging libraries or a numeric address are unavailable.

From the **Screens** card on any paired guest's dashboard, pick an item from the
shared queue and press **Play**. Screens are independent targets: controlling
one never stops, replaces or takes over the host's own Cast or DLNA playback.
Play, pause, resume, seek, stop and volume are sequenced per screen; an
identical retried command returns its original receipt, and a late report about
an earlier item cannot overwrite a newer one. Starting an item from the card
also makes the screen *follow the queue*: when an item finishes, the next
playable one starts. Unplayable entries are skipped rather than stalling.

**Delivery.** The browser tells the host which container types it can decode.
If it can decode the file's container, SmoothCast serves the original file with
byte-range support (**direct**). If a direct stream fails because of an
unsupported codec, the screen asks for the converted stream automatically.
For other formats (for example AVI or AIFF) the host runs FFmpeg to produce a
progressive fragmented MP4 (**converted by host**): at most two conversions run
at once, they run at below-normal priority, they are killed the moment the
screen disconnects, and a converted stream that drops while paused resumes at
the same position. Seeking a converted stream restarts it at the new position.

**Security and limits.**

- Screens, polling, commands and media require a paired session cookie. Every
  state-changing request also needs the CSRF token and a matching Host/Origin.
  Only the session that registered a screen may poll or report for it; any paired
  participant may send commands, like the shared queue.
- Media is addressed only by the room's opaque queue IDs and only items
  currently in the shared queue can be streamed. Host paths never reach a
  browser; symlinks, directories and files that vanished are refused at open time.
- Removing a guest or signing everyone out removes their screens immediately and
  blocks further media reads. A screen that stops contacting the host is shown as
  not responding after 12 seconds and removed after 30.
- At most 8 screens, 8 concurrent media streams and 2 conversions per room.
- The host can turn guest screens off in **Preferences > Playback > Shared room**;
  media requests are then refused with a clear message.
- The room still uses plain HTTP on a trusted LAN (see below). Media sent to a
  screen is visible to that LAN segment in the same way as the dashboard.

## YouTube and BitTorrent link acquisition (#587)

In **Up Next → Add a link to Up Next**, a paired guest can submit one YouTube
video or BitTorrent v1 magnet, confirm their authority to acquire the media,
and watch the acquisition in the same room feed as other guests. The network
view shows the room host's active jobs as well. Pending acquisition is not
playback: the ordinary queue changes only after the host validates the complete
file and accepts the queue operation. The current receiver is never taken over.

The initial executor is the **room host**, not a randomly chosen mesh node.
One active worker and at most four outstanding jobs per room; the same
canonical source is coalesced, and a retried browser request has a receipt.
The list shows pending/resolving/downloading/verifying/queueing/ready or a
failure/cancellation. Bytes and rates come from worker reports; unknown totals
remain indeterminate. No source URL, tracker, infohash, host path or peer IP
is published in the acquisition feed. The submitting guest can cancel before
the file enters Up Next.

External acquisition defaults to **off**. The owner can enable the YouTube
and BitTorrent switches in **Preferences → Playback → Queue behaviour**,
or set `portal_link_youtube` and `portal_link_magnet` in the local
configuration. Restart the room for a change to take effect. Each enabled provider requires its
host-installed executable (`yt-dlp` or `aria2c`), FFprobe, and an absolute
executable path in the host environment variable `SMOOTHCAST_LINK_SANDBOX`.
The launcher must enforce the local owner's egress and filesystem policy:
deny internal/private/link-local destinations (including DNS rebinding),
expose only the job staging directory and required read-only runtime,
enforce a hard disk quota, and kill the entire descendant process tree.
It receives the executable and individual arguments, never a shell command.
**Do not use a pass-through launcher**. SmoothCast cannot attest an arbitrary
launcher's OS-level restrictions. Automatic cross-platform sandbox setup and
real-provider qualification are outstanding; unavailable workers are shown as
unavailable instead of silently attempting unrestricted downloads.

The first slice accepts HTTPS single-video YouTube links (not playlists or
active live streams) and v1 public magnet infohashes. Guest tracker/webseed
parameters are discarded. BitTorrent metadata is acquired first via DHT,
matched to the requested infohash, checked for unsafe paths and aggregate
size, and the largest supported audio/video file is selected. Private,
v2-only, unsafe or oversized torrents are rejected. No post-download seeding
is requested. The per-job maximum is 2 GiB, with a 512 MiB disk reserve and a
30-minute time budget. Only completed readable audio/video is offered to Up
Next; acquisition does not bypass DRM or access controls. Acquire only media
you are entitled to download.

Available workers advertise `acquire-youtube-local` and/or
`acquire-magnet-local` in existing mesh node capabilities. These mean the
node can run the indicated local provider, not that it accepts remote jobs.

**Remaining work:** authenticated remote assignment, mesh-wide job telemetry
and verified node-to-node delivery,
restart-safe leases/resume, owner settings and worker provisioning. Follow
[#587](https://github.com/gmanldn/smoothcast/issues/587). Do not interpret the
room-local live view as proof of remote execution.

## Recovering a room queue

While a room is running, SmoothCast checkpoints the ordered queue into a
private file on the host. The file contains local media references and a format
version. On restart, **Recover queue** restores available items in order and
reports missing files or unfinished uploads. **Discard previous room** clears
the checkpoint. If the queue changes while the prompt is open, the current
queue is kept.

Recovery does not start playback or restore guest sessions. Guests rejoin the
current room using its current access settings.

## Access and privacy

- A new unpredictable PIN is generated each time the portal starts or changes
  interfaces, but it is only required when **Require a house PIN to join** is
  enabled. The PIN uses six digits so it is easy to read aloud. With the switch
  off (the default), the login page shows only a name field and joins
  immediately; a name already remembered by the browser joins on load.
- After joining, the browser receives a temporary, HTTP-only, same-site session
  cookie tied to one named participant. Sessions expire after eight hours or
  when the room stops. Reloading the page after expiry resumes the same
  session when the cookie is still valid, otherwise it asks for the current
  PIN if the House PIN is enabled. Up to 32 named participants are shown;
  duplicate names receive a stable numeric suffix. Guests can update only their
  own display name. The active roster drops clients after 45 seconds without
  authenticated activity; reconnecting with the still-valid session restores
  the same identity and nickname. Dormant identity retention is bounded and
  ends with session expiry.
- When the House PIN is enabled, five incorrect PIN attempts from one client
  are rate-limited. The PIN, session cookie and PIN-entry request are not
  written to SmoothCast logs.
- Every state-changing request checks the allowed Host and Origin and requires
  a per-session CSRF token. Queue entries are addressed by opaque short hashes,
  never by host filesystem paths. Guests cannot request arbitrary filesystem
  paths or arbitrary URL fetches. New media can arrive from uploaded files,
  shared libraries, or explicitly enabled, isolated link acquisition.
- On the trusted home LAN, being on the Wi-Fi is the invitation. When the
  optional House PIN is enabled it becomes the room authority. Use the room
  only on a trusted LAN, keep the desktop screen and any House PIN private, and
  close SmoothCast to stop the listener. There is no separate cloud account or
  room server.
- Uploads use sequential 2 MiB HTTP chunks with bounded 64 KiB server reads.
  **Add to the shared queue** is selected by default for every authenticated
  participant. It disables early casting, so a partial video is never offered
  to the receiver; the completed file is queued instead. Audio is always
  validated and queued, never cast directly. For videos, clearing the selection
  is an explicit play-now request and may start an early cast.
  Each acknowledged chunk is synced to disk; an interrupted chunk rolls back to
  its starting offset, and the browser resumes from the server's confirmed byte
  count. Multiple selected files upload sequentially with per-file progress; a
  retry resumes the current file before continuing the batch. The browser never
  reads the entire media file into memory.
- Uploads are staged in a mode-0700 cache directory with mode-0600 partial
  files. At most three transfers can be active and a 512 MiB free-space reserve
  is kept. Videos use the supported video suffixes. Audio accepts MP3, AAC,
  M4A, FLAC, Ogg, Opus, WAV and AIFF up to 512 MiB and 24 hours; SmoothCast
  probes the completed file and requires a readable audio-only stream before it
  enters Up Next. Audio is always queued and never early-cast. Incomplete
  transfers are discarded when the portal stops and stale partials older than
  24 hours are removed.
  Completed media files are retained because active/recoverable cast sessions
  may still read them.
- The dashboard reports transfer progress and supports cancellation. Keep the
  dashboard open to resume from the server-confirmed byte count if automatic
  retries are exhausted. A fully
  received and size-checked staged file is passed to SmoothCast's normal cast
  path, which performs server-side media probing, transcoding and device
  streaming.
- **Casting while a file is still arriving.** For a large upload of a
  progressively readable container (MKV, MPEG-TS, WebM, or a faststart MP4 whose
  index precedes its media data), SmoothCast starts casting as soon as a small
  buffer has been received, then keeps streaming the rest of the file to the
  instance automatically. The cast is transcoded to HLS (never direct-played),
  so the receiver is never handed a partial file. The staged path stays stable
  while the cast reads it, so the transfer never interrupts playback. FFmpeg
  reads the growing file at the playback rate, so the transfer stays ahead of
  the cast on a local network.
- Formats whose index is at the end of the file (for example a non-faststart
  MP4) cannot be probed or cast until they are complete, so they are cast from
  the finished file. If an early cast cannot start, the completed file is cast
  instead; no upload is lost.
- The Shared room card shows up to four active participant names and what
  connected clients are doing: each upload's
  name, progress, transfer rate, phase (receiving, casting while receiving, or
  received) and the client address. The browser shows the same state, including
  "Casting now" once an early cast has started.
- The listener binds only to a private RFC 1918 address chosen by SmoothCast;
  it never binds to all interfaces, a public address or a router port-forward.
  If no usable private IPv4 address is available, the card reports that the
  LAN portal is unavailable and does not show a PIN.
- SmoothCast checks for interface changes every 15 seconds. If its chosen
  address changes, the old listener and sessions are stopped, then a new URL
  and PIN are generated.

The portal uses plain HTTP for compatibility with ordinary local browsers.
Anyone who can reach the selected LAN interface can see the login page; with
joining open by default, anyone on that LAN can control playback unless the
House PIN is enabled. Use it on a trusted local network and keep the SmoothCast
screen and any House PIN private. Closing SmoothCast stops the listener.

## Verification

Portable tests exercise PIN creation, rate limits, authentication, open join
with and without the House PIN, Host/Origin
and CSRF checks, named presence, self-service rename, inactive roster expiry,
session reconnect/expiry, queue votes, queue actions,
resumable staged uploads, queue-only uploads, early-cast selection and fallback,
activity summaries, HTTP responses, and clean listener shutdown on loopback.
They do not verify reachability from a phone or another LAN host, nor real
transcoding of a growing file on a device.
The isolated GUI smoke checks that the shared-room card builds; real second-device
and physical playback-control checks remain device qualification.

## Mesh (experimental, off by default)

Full nodes on the same LAN can discover each other and share a live inventory of
nodes, connected browsers and Cast/DLNA/browser targets (design:
[MESH_DESIGN.md](MESH_DESIGN.md), threat model: [MESH_SECURITY.md](MESH_SECURITY.md)).
It is disabled until the Network view ships. To try it, add to
`~/.config/cast-control/config.json`:

```json
{"mesh_enabled": true, "mesh_seeds": ["192.168.1.20"], "mesh_strict": false}
```

`mesh_seeds` are optional private addresses to contact when multicast is blocked;
`mesh_strict` only lets nodes already seen by presence discovery sync with you.
Turning `mesh_enabled` off restores the exact previous behaviour: no sockets and no
threads. Paired browsers can read the live view at `/api/mesh` and `/api/mesh/events`
(Server-Sent Events). The mesh runs on its own thread and its failures never affect
playback or the portal; `mesh_service.MeshService.diagnostics()` reports redacted health.

## Room event reconnects

Authenticated `/api/events` streams expose a random per-server `stream_epoch`
and monotonically increasing `epoch:sequence` SSE IDs. On reconnect, clients
may supply the standard `Last-Event-ID` header. SmoothCast replays available
events **for the authenticated participant only**, then always sends a complete
current snapshot. Missing, invalid, expired or previous-server IDs never block
reconnection; the fresh snapshot includes `stream_resync: gap`, `invalid` or
`restarted` when appropriate. The cache retains at most 128 state frames of
at most 64 KiB each globally; revoked and expired guests lose their history.
The existing `/api/status` polling fallback remains available.

## Joining and using the room (guest quick start)

The room is designed for **first-time guests**. Open the link shown on the
SmoothCast desktop host while connected to the same local Wi-Fi. You do not
need a separate account or app. Enter a display name and, **only if the host
has enabled it**, the six-digit House PIN. With an open room, the PIN field
disappears. After joining, the dashboard shows **Joined as your name** with a
**Change name** link to the room's name editor. This identity is returned by
the host, rather than taken from unsubmitted text in the browser. Room controls
affect the shared selected receiver and queue, not just the browser on your phone.

The dashboard is organised in the order a new guest needs it:

1. **Now Playing** — read the receiver, title and state; play/pause, seek,
   skip, stop or change the *receiver* volume. These affect everyone using
   that receiver.
2. **Find** — search host-shared films and music, filter available titles and
   browse libraries.
3. **Add files** — upload from your own phone/computer. **Add to Up Next**
   is checked by default and leaves the current playback uninterrupted.
   Audio is always queued. Unticking the option for video may start it early.
4. **Up Next** — vote, play an item now, make it next, move it up/down or remove
   it. Clearing the entire shared waiting list requires confirmation; it does
   not stop the current cast.
5. **Screens** — open the room's screen page on a TV, tablet or laptop to
   make that browser a separate playback target. Give the screen a name,
   enter the House PIN only if required, and tap **Start screen** to allow
   audio. Screen playback is independent of the host's TV or speaker.
6. **People** — view participants and recent activity, or change your name.
7. **More settings and network information** — optional lock-screen controls,
   wake lock, audio normalisation, other hosts and read-only receiver activity.

The connected dashboard also shows a copyable room link near the top. It
contains only the local address, never a PIN or session credential. When a
browser cannot use the clipboard on local HTTP, the link is selected for
manual copying instead of silently failing.

When a mesh is running, the section navigation adds **Network**. It is
hidden when mesh discovery is unavailable, rather than linking to an empty
panel. Network shows cooperating SmoothCast computers and the TV/speaker
targets they can reach. The expandable help explains Ready, In use, Not seen
lately and Can't be reached; the panel is read-only and does not start or
stop a cast. The **Screens** section has its own touch-accessible help and
only enables Play when a queued item is selected and the target responds.
Its controls and keyboard focus survive normal status polling, even when a
screen changes between Playing and Paused. Each command reads the latest screen
state, and a selection disappears safely if its queue item is removed. If a
screen disconnects while its controls have focus, focus returns to the Screens
heading instead of being lost. Rapid repeated taps are coalesced **per
screen** while a command is awaiting acknowledgement; other screens can still
receive commands independently. In-flight buttons remain focusable with an
accessible busy state. Replies from an expired session do not overwrite
messages for a newly joined room.

Mesh discovery runs one snapshot request at a time and cancels pending
requests when the guest leaves or backgrounds the tab. Late responses cannot
reopen the Network panel or event stream after room access changes.

Help is available **next to the relevant action** using touch-, mouse- and
keyboard-operable disclosure controls, with additional desktop hover titles.
These explain side effects and unavailable actions; tooltips are not required
to discover the main journey. The layout is one column on phones and a
two-column workspace on larger screens, using the existing light/dark colour
tokens. The web room remains entirely self-hosted and uses the existing
session, CSRF and command protocols.


## Upload resumption file-recognition safeguard

Browsers store only upload-session metadata in IndexedDB, not the selected
media bytes. When a visitor reselects a file after reconnecting, the browser
compares its name, size, modification time and a bounded file fingerprint before
continuing. New v3 fingerprints sample the first, middle and last 64 KiB (at
most 192 KiB read), keeping the browser responsive even for enormous media.
Previously stored v1/v2 fingerprints are still recognised. Older v1 calculations
have an 8 MiB maximum even if browser storage contains malformed metadata.

This is **accidental-substitution detection**, not cryptographic whole-file
verification. A file with changes only outside these samples may still match;
end-to-end SHA-256 checking for copies/transfers belongs to the transfer
integrity protocol (#569/#357). The server's sequential offset, ownership,
root containment and durable-write checks remain authoritative.

## Browser file-transfer throughput contract (issue #568, first slice)

- The room advertises an **8 MiB maximum chunk** in the upload-creation
  response. The browser uses that negotiated size and sends sequential
  `Content-Range` chunks. Existing 2 MiB clients remain supported.
- The server reads and writes chunks through a **64 KiB buffer**; it does not
  retain an 8 MiB upload body in memory.
- A successful PUT is acknowledged only after **`fsync`** has completed for
  its chunk. Increasing chunk size reduces request and sync frequency for large
  files but does **not** implement crash-persistent upload sessions, coalesced
  durable checkpoints or guaranteed recovery after the host process restarts.
- Validated upload PUTs have a bounded **30-second socket read timeout** for
  slower Wi-Fi; ordinary room requests retain their shorter timeout. A failed
  or interrupted chunk is rolled back to its last acknowledged offset.
- Speed-up depends on the storage device, RTT and Wi-Fi link. No throughput
  improvement is claimed without measured benchmarks (#573). Adaptive chunk
  negotiation and cross-restart durable offsets remain tracked in #568.
