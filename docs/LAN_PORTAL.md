# SmoothCast shared room

When the SmoothCast desktop app is running, it starts a small web room on the
selected private LAN IPv4 interface. The **Shared room** card on the main
screen shows the address and a six-digit PIN. Open that address in a browser on
the same local network, enter your name and the PIN, and you join a shared
queue with everyone else in the room. The app remains the single owner of the
queue and the receiver; web actions are marshalled onto the GTK thread.

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
The room also shows live presence and a bounded activity feed. Votes are a
visible signal and are preserved across refreshes; queue order remains under
the room's control so nobody's film can be silently displaced.

The **On your network** card in the desktop app and dashboard lists currently
playing, buffering or paused media reported by reachable Cast and DLNA
receivers discovered on the LAN. It refreshes every 15 seconds, shows the
receiver, media title and available progress, and never sends commands to those
other receivers. Unreachable devices are omitted; titles in the dashboard are
visible only after PIN pairing.

The **Nearby SmoothCast hosts** list uses a separate, versioned DNS-SD record
to show other SmoothCast instances on the LAN. It contains only a random
instance identifier, friendly host name, protocol version and capability names;
it does not contain a PIN, session, user nickname or media path. Opening another
host takes the browser to that host's own PIN prompt. Discovery alone cannot
transfer a file or issue Cast commands. If multicast discovery is unavailable,
the UI reports that state rather than implying that no peers exist.

The address is a friendly mDNS name such as
`http://smoothcast-lounge.local:PORT/`. SmoothCast derives the name from the
machine hostname, prefixes it with `smoothcast`, and advertises it with
mDNS/Bonjour when the `zeroconf` dependency is available. The card also shows
the numeric IP address as a fallback for networks that block multicast DNS.

Scan the room QR with your phone camera to open the numeric room link,
then enter the PIN shown on the host. The QR is generated locally and contains
only the address. You can also use **Copy link**.

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

## Access and privacy

- A new unpredictable PIN is generated each time the portal starts or changes
  interfaces. The PIN uses six digits so it is easy to read aloud.
- After pairing, the browser receives a temporary, HTTP-only, same-site session
  cookie tied to one named participant. Sessions expire after eight hours or
  when the room stops. Reloading the page after expiry asks for the current PIN
  again. Up to 32 named participants are shown; duplicate names receive a
  stable numeric suffix. Guests can update only their own display name. The
  active roster drops clients after 45 seconds without authenticated activity;
  reconnecting with the still-valid session restores the same identity and
  nickname. Dormant identity retention is bounded and ends with session expiry.
- Five incorrect PIN attempts from one client are rate-limited. The PIN,
  session cookie and PIN-entry request are not written to SmoothCast logs.
- Every state-changing request checks the allowed Host and Origin and requires
  a per-session CSRF token. Queue entries are addressed by opaque short hashes,
  never by host filesystem paths. The room has no file browser, arbitrary
  filesystem path or arbitrary URL cast; uploads are the only way to introduce
  new media.
- The PIN is the room authority. Use the room only on a trusted LAN, keep the
  desktop screen and PIN private, and close SmoothCast to stop the listener.
  There is no separate cloud account or room server.
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
  and PIN are shown.

The portal uses plain HTTP for compatibility with ordinary local browsers.
Anyone who can reach the selected LAN interface can see the login page; anyone
who also knows the displayed PIN can control playback. Use it on a trusted
local network and keep the SmoothCast screen and PIN private. Closing SmoothCast
stops the listener.

## Verification

Portable tests exercise PIN creation, rate limits, authentication, Host/Origin
and CSRF checks, named presence, self-service rename, inactive roster expiry,
session reconnect/expiry, queue votes, queue actions,
resumable staged uploads, queue-only uploads, early-cast selection and fallback,
activity summaries, HTTP responses, and clean listener shutdown on loopback.
They do not verify reachability from a phone or another LAN host, nor real
transcoding of a growing file on a device.
The isolated GUI smoke checks that the shared-room card builds; real second-device
and physical playback-control checks remain device qualification.
