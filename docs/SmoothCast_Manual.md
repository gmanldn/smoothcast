# SmoothCast Manual

**Product guide and technical reference | develop v2.3.11 | 27 November 2026**

Source snapshot: [38270735f2092089f58a34e1100d45923ac07410](https://github.com/gmanldn/smoothcast/commit/38270735f2092089f58a34e1100d45923ac07410). PDF: [SmoothCast_Manual.pdf](SmoothCast_Manual.pdf). This manual replaces the supplied v2.0.8 brochure as an expanded guide. Implementation is not equivalent to native qualification.

## PART I — User guide

### A better way to enjoy media

*Play it. Improve it. Cast it. Let the whole room join in.*

**The difference**

SmoothCast combines a media player, an adaptable casting engine, a shared queue and a browser-based room in one local-first product. Instead of passing one remote around or asking every guest to install an app, the host opens a room and everyone on the trusted Wi-Fi can take part.

**What makes it distinctive**

The same experience joins local files, different screens, sound enhancement and group participation. Compatible media can travel unchanged; incompatible media can be prepared for the destination. The host remains in control while others contribute.

**World-class by design**

Our ambition is a class-leading experience: effortless entry, responsive controls, honest feedback, privacy and resilience. These are engineering priorities, not an independently benchmarked claim of market superiority.

Sources: README.md; docs/PRODUCT.md; docs/VISION.md

### Get started in minutes

*One computer hosts the experience. Everyone else needs a browser.*

**Install and open**

On Linux or macOS, use python3 sc.py from the extracted source folder. On Windows with the Python launcher, use py -3 sc.py. Python 3.10+ is required for the source launcher. Initial setup may install dependencies and require network access or package-manager approval. Linux, macOS and Windows have distinct native qualification status.

**Choose something to play**

Open a video or audio file, preview it, choose the output and use Cast to TV or local playback. If a receiver is absent, check that it supports the required protocol and that the devices share a reachable network. An ordinary Wi-Fi television is not necessarily a Cast receiver.

**Invite the room**

Open the room link or scan its QR code. Enter a name, and the House PIN only if enabled. Guests can contribute from phones, tablets and laptops without installing SmoothCast. The host can revoke sessions.

Sources: README.md; setup/README.md; docs/LAN_PORTAL.md

### A room that belongs to everyone

*Make a film night or music session a genuinely shared experience.*

**Join the room**

The host shares a local link or QR. A friendly network name can be easier to remember than an IP address; the numeric address is a useful fallback. The host can name the room. Joining is open by default on trusted Wi-Fi; enable a House PIN when appropriate.

**Build Up Next together**

Add songs or videos, vote, reorder, remove, make next or play now. Votes express preference without secretly changing the queue. A guest can clear upcoming items without stopping the film that is already playing.

**Keep the experience coordinated**

See who's here, what's playing and relevant activity. Play, pause, seek, skip, stop and adjust receiver volume where supported. A refused or pending action is not presented as a completed one. The room host owns its queue and playback authority.

Sources: docs/LAN_PORTAL.md; docs/PRODUCT.md; #709

### Your browser is the remote

*A phone should be a first-class way to participate, not an afterthought.*

**One coherent home**

Find media, view Now Playing, contribute to Up Next and see available screens and network activity. On a small phone, essential actions remain easy to reach. The browser needs no external web app, account or guest installation.

**Add or play**

Choose a file to add to the shared queue, or use Upload & Cast Now for a suitable video. Confirm the named receiver before transferring for immediate playback. Audio contributions are queued rather than interrupting the room.

**What the feedback means**

A request may be waiting, accepted, transferring, checking, refused or confirmed. Transfer completion does not prove playback. The room updates status and activity so users can understand what has happened. Some advanced desktop settings are still host-only.

Sources: docs/LAN_PORTAL.md; docs/WEB_TRANSFER_JOURNEY.md; docs/WEB_DESKTOP_PARITY.md

### Bring media from your phone

*No cables, no passing around USB drives and no need for guest setup.*

**Contribute a file**

Choose audio or video from your device. Queueing is the safe default. Suitable video may begin casting while it arrives if you explicitly request playback. Other media waits for validation and completion.

**Stay informed**

The browser displays acknowledged bytes, progress, measured transfer speed and approximate remaining time. Pause, resume or cancel a transfer. Reselect the same file when required; the host checks its identity and tells the browser where to resume.

**Protect the host**

Uploads use private staging and bounded storage. A full disk, a changed target or a lost connection should produce a clear explanation. The file remains on your device unless you choose to remove it. Automatic uninterrupted uploads after closing the browser are not promised.

Sources: docs/WEB_TRANSFER_JOURNEY.md; src/portal_uploads.py; #568/#570/#572

### Find something to play

*Your own shared collection comes first. Optional external sources broaden the experience.*

**Your household library**

Find media the host has chosen to share. Search by title and media type, use available results and add them to Up Next. A library may span participating nodes; availability depends on sharing and network reachability.

**External discovery**

When the owner explicitly enables a qualified provider, the room can search YouTube and request acquisition of an authorised single video. A supported public BitTorrent v1 magnet may be submitted when a suitable isolated worker exists. Search itself does not download.

**From request to ready**

The acquisition feed shows real progress, verification and queue acceptance. External workers are disabled by default; no guest installs tools. Only request content you are entitled to obtain. The reference Linux sandbox does not support BitTorrent peers; live provider qualification is outstanding.

Sources: docs/LAN_PORTAL.md; docs/LINK_SANDBOX.md; docs/MESH_SEARCH.md; #588

### Every screen has a role

*Turn a spare device into a screen or a speaker, not just a remote.*

**Cast to a receiver**

Choose a compatible Google Cast device, such as Chromecast or a TV with built-in Google Cast. A compatible DLNA/UPnP MediaRenderer is another beta option. The host checks compatibility and prepares media as needed.

**Use a browser as a screen**

Open the room's /screen page on a tablet, laptop or compatible TV browser. Name it, join and press Start screen once to allow sound. A paired participant can then choose an item and direct it to that screen.

**Keep sessions separate**

A browser screen can play independently of the main Cast or DLNA receiver. Use a phone with headphones as a private speaker. Multiple independent browser outputs are not synchronised multi-room audio. Codec support, browser autoplay rules and host resources affect results.

Sources: docs/LAN_PORTAL.md; docs/DEVICE_COMPATIBILITY.md

### The player puts the film first

*Preview, inspect and choose before handing playback to another screen.*

**Preview and navigate**

Open local media and inspect its duration, tracks and picture. Scrub on the original film timeline rather than a confusing converted-stream clock. Cached thumbnails and exact-position preview work reduce redundant preparation; performance depends on the media and machine.

**Make it your version**

Select a preferred audio language or subtitle track. Use captions, adjust timing, choose a playback speed or rotate the image where supported. Picture controls include brightness, contrast, saturation and hue, with neutral defaults and per-film presets.

**Keep your place**

Remembered positions and playlists let you come back later. Queue filters, reorder controls, repeat-one and M3U save/load keep your library practical. Screenshots can be taken without making the interface wait for FFmpeg.

Sources: README.md; docs/CHAPTER_NAVIGATION.md; docs/PICTURE_ADJUSTMENTS.md; docs/SPARSE_THUMBNAILS.md

### Hear the words. Feel the film.

*Intelligent sound for real rooms, headphones and late-night viewing.*

**Original**

Keep the original sound profile when you do not want automatic dynamic processing. The delivery path may still require format conversion or stereo downmixing; Original is not a promise of bit-perfect passthrough in every mode.

**Dialogue**

Automatic trim, compression, limiting and a centre-weighted mix on recognised surround layouts help speech remain audible amid action. Live meters show input, output and gain reduction where available, so you can see the processing.

**Night**

Stronger compression reduces sudden changes in volume. Optional loudness targets and lip-sync adjustment provide further control. These features operate on supported processing paths, not every receiver, and do not change your computer's system volume.

Sources: README.md; docs/agents/preferences.md

### A library that fits your life

*Keep the media you already own rather than reorganising it for every screen.*

**Formats**

Common source containers include MKV, MP4, MOV, WebM, AVI, M4V and MPEG-TS. Audio sources include MP3, M4A/AAC, FLAC, Ogg/Opus, WAV and AIFF. Actual decoder support depends on FFmpeg and the target.

**Adapt instead of giving up**

Where compatible, send the original media. Otherwise SmoothCast can convert it to a supported stream. On a slow host, conversion takes resources; a DLNA film may need to be fully prepared before playback. Supported HDR10 can be tone-mapped to SDR on conversion.

**Subtitles and accessibility**

Choose sidecar or embedded captions where supported, adjust caption timing, or burn captions into converted video. Browser parity is evolving; advanced track, picture and preview controls are not all available in the web room. AirPlay, Miracast and DRM playback are not promised.

Sources: README.md; docs/HDR_TONEMAP.md; docs/WEB_DESKTOP_PARITY.md

### One household, many doors

*The mesh brings devices, rooms and shared media into a coherent network view.*

**See the house**

Full SmoothCast nodes discover one another and exchange bounded information on membership, reachable targets, capabilities and activity. The Network view combines people, nodes and connection detail. Nearby hosts can have their own rooms.

**Share deliberately**

Authorised shared folders can contribute to a replicated catalogue. Implemented node-to-node range streaming can serve or proxy available content. The user experience should choose a sensible route, but not all automatic multi-node transfer and routing journeys are complete.

**The ambition**

One coordinated home with smart workload placement, receiver-safe handoff and seamless recovery is the product direction. Mesh observation does not grant control of another receiver. Cross-node job assignment and verified delivery are still being developed.

Sources: docs/MESH_DESIGN.md; docs/MESH_PROTOCOL.md; docs/MESH_SEARCH.md; #589

### Your media stays yours

*Privacy and local control are central to the experience.*

**Local by default**

SmoothCast is self-hosted; the room does not need a separate cloud account or server. Room links are for trusted local networks. Enable external acquisition only deliberately, because those providers contact the internet.

**Know the boundary**

The room uses plain HTTP, not end-to-end encryption. Anyone on the same LAN segment may observe traffic. A House PIN limits joining but is not a replacement for network isolation. Do not expose the room to the public internet or open inbound router ports for it.

**Control the experience**

The host chooses shared folders and permissions, can sign guests out, and can disable guest screens or acquisition. Guest browsers should not see arbitrary host paths or credentials. Logs and local diagnostics are bounded and designed for redaction.

Sources: docs/PORTAL_THREAT_MODEL.md; docs/LAN_PORTAL.md; docs/MESH_SECURITY.md

### When something does not work

*Good software helps you recover, rather than making you guess.*

**Receiver not found**

Check that the target actually supports Cast or DLNA, is powered on and on a reachable LAN. Try the numeric private IP for a Google Cast receiver if multicast discovery fails. Client isolation, VPN routing and firewall restrictions can prevent communication.

**Media will not play**

Try a compatible file, select a different supported track or remove a transform temporarily. Check FFmpeg 5.0+ and the host's available CPU and storage. DLNA may require lengthy preparation; browser sound may need a Start screen tap.

**After an update**

An already-running process cannot become a new version simply because files were pulled. Finish playback, quit normally and relaunch. The displayed version and build identity should reflect the actual code loaded; on Linux a clean registered checkout can refresh the installed copy. Other platforms may need explicit setup.

Sources: README.md; docs/ERRORS.md; docs/UPDATE_ARCHITECTURE.md; docs/CAST_RECOVERY.md

## PART II — Technical reference

### Architecture and authority

*Technical reference | Runtime boundaries, ownership and failure containment.*

**Desktop and process domains**

Python 3.10+, GTK4/libadwaita, FFmpeg/FFprobe and protocol adapters form the desktop runtime. GTK owns window and shared room mutations. Media preparation, discovery, subprocesses and network work run outside the UI domain and return fenced results. A room host owns the queue and its receiver session; an independent browser screen owns a separate playback context.

**Control plane versus data plane**

Cast/DLNA commands control the receiver, while the media path is direct HTTP, HLS or prepared MP4. Browser HTTP/SSE and status snapshots expose control and progress. The mesh exchanges membership, library and read-only activity independently of receiver ownership. Do not treat an observation, an accepted command or a transfer acknowledgement as playback.

**Principal modules**

sc.py, setup/launch.py and src/cli.py select runtime and startup. cast_control.py and cast_ui.py orchestrate desktop presentation; cast_session.py, cast_queue.py, castctl.py, streamer.py, server.py and dlna.py coordinate sessions, queue, transport and serving. portal.py, portal_room.py, portal_commands.py and portal_uploads.py provide room services. Refer to module contracts and tests for exact signatures.

Sources: README.md; docs/INVARIANTS.md; docs/ASYNC_WORKERS.md; docs/agents/architecture.md

### Media pipeline and capability selection

*A predictable path from source inspection to receiver-confirmed playback.*

**Preflight and routing**

Probe selected streams with FFprobe; resolve the target, media characteristics and required transforms before disturbing playback. Select the private interface routed to the receiver. Compatible direct playback preserves source bytes; explicit track selection, speed, rotation, captions or picture transforms may require conversion. A compatible remux preserves codecs while changing container.

**Cast HLS and fallback**

FFmpeg 5.0+ is required. Video transcoding targets H.264 8-bit 4:2:0 and AAC; Linux can use VAAPI with bounded libx264 fallback. macOS/Windows initially use software encoding. Software output is bounded to 1080p and high-frame-rate sources to 30 fps for older receiver compatibility. Audio-only Cast uses AAC HLS without dummy video. HLS generation tokens isolate stale requests.

**DLNA and browser routes**

DLNA uses SSDP discovery and UPnP SOAP AVTransport; ConnectionManager may expose format constraints. Compatible MP4 is direct, compatible MKV remuxed, incompatible tracks/subtitles prepared before dispatch. Browser delivery uses ranged original bytes or bounded fragmented MP4 conversion. Neither the synthetic decoder matrix nor fake receiver tests establish physical interoperability.

Sources: README.md; docs/PLAYBACK_MATRIX.md; docs/RECEIVER_LEARNING.md; docs/DEVICE_COMPATIBILITY.md

### Audio processing and source time

*Signal processing choices have explicit effects on delivery and clock semantics.*

**Audio filters**

Dialogue and Night use automatic input trim, acompressor and limiter. Recognised 5.0/5.1/6.1/7.1 and quad layouts use centre-weighted stereo downmix: roughly +5 dB centre weighting relative to the default FFmpeg mix, lowered surrounds and dropped LFE. Unknown layouts and Original use the normal stereo downmix. Live input/output and gain reduction meters are bounded.

**Loudness and timing**

Optional EBU R128 targets: programme -16 LUFS, album -18 LUFS, with -1.5 dBFS true-peak limiting; off by default and applies to transcoded audio. Selected language and audio delay are host controls. Source-time mapping accounts for seek offsets and 0.5x-2x speed, preventing HLS segment time from replacing film position.

**Subtitle and picture pipeline**

External SRT/VTT/TTML/ASS/SSA, sidecar detection and supported embedded text/bitmap tracks are path-dependent. Burn-in is a transform. Brightness [-0.5,0.5], contrast [0.5,1.5], saturation [0,2], hue [-180,180] degrees: neutral defaults 0/1/1/0. HDR10 recognition requires explicit PQ/BT.2020 metadata; zscale + Hable tonemap converts to BT.709 SDR before subtitles. HLG/Dolby Vision are separate work.

Sources: README.md; docs/PICTURE_ADJUSTMENTS.md; docs/HDR_TONEMAP.md; docs/SUBTITLE_SCRUB_PREVIEW.md

### Discovery, receiver state and lifecycle

*Separate evidence of reachability, ownership and confirmed playback.*

**Discovery**

Google Cast uses mDNS and a Cast backend; manual private IPv4 is a fallback for known Cast receivers. DLNA uses private IPv4 SSDP and matching device-description host validation. Network inspection is read-only and never seizes playback. Device records and route evidence should be treated as expiring observations, not immutable capability claims.

**Session fences**

Preflight before replacing an active cast. Use generation identities and source/receiver ownership to reject stale callbacks and cross-session mutations. Direct-first status probing for verified private Cast targets preserves time for a fallback rather than spending the whole budget on a slow subprocess. Receiver PLAYING confirmation is distinct from command acceptance.

**Recovery and teardown**

Bounded retries and watchdog recovery avoid endless loops. Preserve existing playback on a failed new preparation. DLNA scratch files have process-held leases, disk caps and age-based recovery; the default scratch cap is 8192 MB (0 unlimited). DLNA listener lifetime is tied to the application. Do not terminate another process on PID alone; verify ownership and generation.

Sources: README.md; docs/CAST_RECOVERY.md; docs/INVARIANTS.md; #712/#686

### Room protocol and concurrency

*A LAN web server with an explicit authoritative model.*

**Session and routes**

Python standard-library HTTP server binds to a selected private LAN address and OS-assigned port. /api/login establishes a session cookie and per-session CSRF token. Mutations need Host/Origin validation and CSRF. Public read-only routes and declared route capabilities are enumerated in src/api_spec.py and the OpenAPI document.

**Mutation semantics**

Queue revisions fence reorder, remove and clear. Participant-scoped command IDs make retries idempotent; conflicting reuse is rejected. Recent receipts live in a bounded two-minute cache. Clear Up Next never replaces active playback. At most two outstanding commands per participant. Accepted, confirmed, failed and uncertain states must remain distinct.

**Read and presentation paths**

GTK publishes versioned status snapshots for HTTP readers, including snapshot_age_ms, rather than blocking a browser poll on a callback. Stable row IDs preserve touch intent through updates. Coalesced seek and volume actions retain final intent; volume sends at most once per 150 ms while dragging. Browser status reconnects and applies fresh snapshots.

Sources: docs/LAN_PORTAL.md; docs/COMMAND_TRACING.md; docs/TRANSPORT_FEEDBACK.md; docs/api/openapi.json

### Transfer protocol and durability

*Do not confuse transport acknowledgements with persistence or playback.*

**Session contract**

POST /api/uploads allocates an owner-bound private upload; sequential PUT /api/uploads/<id> uses Content-Range. The current chunk ceiling is 8 MiB; the original brochure describes a 64 KiB streaming buffer. A bounded fingerprint helps prevent resuming the wrong file. The host's offset is authoritative; DELETE cancels and /complete finalises.

**Durability semantics**

The newer implementation in portal_uploads.py separates received bytes from committed bytes, coalescing fsync checkpoints by byte/time thresholds and syncing outstanding bytes before completion. Uncommitted data is volatile. Do not equate received with crash-durable committed data. Persistent session recovery and measured throughput qualification must be independently demonstrated (#568).

**Early cast and limits**

Upload & Cast Now confirms and pins the named receiver to the upload ID; a changed target is refused. A 16 MiB progressive heuristic applies to suitable video, not all containers. Audio is queue-only. Private staging, three active uploads and a 512 MiB free-space reserve protect the host. Finalisation validates media; receiver-confirmed PLAYING remains a separate state.

Sources: docs/WEB_TRANSFER_JOURNEY.md; src/portal_uploads.py; #568/#569/#570/#572

### Browser screens and web parity

*Independent playback contexts without mirroring the host desktop.*

**Registration and isolation**

A joined browser opens /screen and registers its named target. Its session owns polling and status; paired guests may issue commands. Screen commands are sequenced and generation-fenced. Revoking the session removes its screens and media access. A screen is not responding after 12 seconds and removed after 30 seconds.

**Serving and conversion**

Opaque queue IDs identify shared items. Reject symlinks, directories and vanished files at open time. Direct bytes support ranges; unsupported codecs can request fragmented MP4 conversion. Limit 8 screens, 8 concurrent streams and 2 conversions per room. Disconnect terminates conversion; seek starts it at the chosen source position.

**Parity boundary**

The web surface has queue, find, timing, volume and network/activity controls. The recorded parity matrix lists gaps for audio/subtitle tracks, picture adjustments and local preview; audio delay and host settings are partial. Host PIN, library folders, credentials and update-channel preferences remain host-local. No host-screen mirroring or synchronized outputs are promised.

Sources: docs/LAN_PORTAL.md; docs/WEB_DESKTOP_PARITY.md; src/portal_screen_page.py

### Mesh membership and replication

*Leaderless data, deterministic roles and explicit reachability.*

**Implemented core**

Wire model, beacon/UDP presence, membership, RPC router, state replication, deterministic primary role, visibility, bounded caches and web clients are documented as implemented. The always-on sc-core coordinator publishes a bounded house snapshot. Current mesh design states enabled by default on a private LAN; legacy brochure described opt-in.

**Replicated state**

Single-writer records, bounded gossip and pull reconciliation limit conflict. Record size capped at 16 KiB; sync replies chunked under 100 KiB. Node and boot identity distinguish restarts; direct evidence can revive a timed-out peer, while second-hand evidence cannot. A primary role is a computed default, not permission to take a receiver.

**Network experience and limits**

The desktop Network popover and browser card show node nature, people and connection detail. Asymmetric reachability matters: seeing another node does not prove it can reach back. Each room retains its authority. Partition healing, global queue and full workload routing must be qualified against actual scenarios; discovery is not remote control.

Sources: docs/MESH_DESIGN.md; docs/MESH_SECURITY.md; docs/MESH_LAN_SMOKE.md; #710

### Library index and file delivery

*Local content identity with explicit shared-folder boundaries.*

**Private index**

SQLite stores authorised local files, stat identity, size, modification time, full SHA-256 and optional FFprobe metadata. Hashing is streamed in 1 MiB blocks; unchanged stat records reuse digest. Defaults: 10,000 files, 10,000 directories and 16 levels. Incomplete scans preserve old rows. No symlink/junction traversal. Optional local-only probe has 12-second timeout.

**Replicated catalogue**

search.v1 uses /mesh/library/generation, /changes, /snapshot and /search. Origin, epoch, sequence and paginated changes fence updates; 410 indicates a reset/compaction. Pages max 5,000 entries, one snapshot per client, approximately 10 requests/s. Only shared entries with relative paths and labels are exposed, not absolute paths, inode or mtime.

**Range streaming**

GET or HEAD /mesh/file/<content_key> supports byte ranges and 416. Serve a shared local file or proxy from an online peer with a matching replica. Forward range and resume at exact byte offset, up to three retries. X-SmoothCast-Hop: 1 prevents proxy loops; max eight streams per node, 503 beyond. Actual complete peer-to-peer transfer qualification is separate.

Sources: docs/LIBRARY_INDEX.md; docs/MESH_PROTOCOL.md; docs/MESH_SEARCH.md

### External acquisition and egress

*Authorised sources, constrained workers, no arbitrary download trust.*

**Job contract**

The guest confirms acquisition authority. YouTube search is explicit and metadata-only; up to ten results, 1-200 character query, one process, 20-second deadline and 512 KiB output budget. Jobs use canonical source deduplication and receipts; one active and four outstanding per room. Stages resolve, download, verify, queue, ready or failure/cancel. Queue acceptance follows complete media validation.

**Sandbox model**

Owner enablement and configured isolation are required. SMOOTHCAST_LINK_SANDBOX points at an executable launcher. Linux bubblewrap reference gives empty home/temp, private PID/IPC and restricted staging. Public-only HTTP(S) proxy resolves and validates every address, blocks private/loopback/link-local/metadata and rebinding, checks redirects, allows ports 80/443, and limits tunnels. It refuses aria2c; a torrent-capable sandbox is separate.

**Qualification and mesh telemetry**

smoothcast --link-check --setup provisions the reference wrapper on supported Linux; --tools-only --qualify checks loopback, IPv6, LAN, metadata, home access and descendants. A verdict binds to launcher digest; optional SMOOTHCAST_LINK_REQUIRE_QUALIFIED=1 enforces it. Cross-node acquisition telemetry is read-only, negotiated per peer and excludes URLs/infohashes. Remote assignment and verified delivery are not proven.

Sources: docs/LINK_SANDBOX.md; docs/LAN_PORTAL.md; docs/MESH_PROTOCOL.md; #588/#589

### Security model and resource bounds

*Trust is explicit; limits and evidence matter more than reassuring labels.*

**LAN boundary**

The portal is plain HTTP on a trusted home LAN; no public deployment or implicit TLS. Open join or optional House PIN; cookie, CSRF and Host/Origin validation defend browser-origin threats. Route capabilities distinguish reads, writes, media, mesh, uploads and acquisition. Public endpoints and residual risks are documented; central enforcement and broader source/egress unification remain tracked in #702.

**Bounded requests**

Token buckets per authenticated participant: reads burst 16/refill 4 per second; mutations 12/6; uploads 40/20. 429 includes Retry-After. Two outstanding commands per participant; at most 512 recent participant/route buckets. Upload staging private (POSIX 0700 directories, 0600 partials); opaque IDs and range validation limit file access.

**Secrets and local data**

Local library/cache/config and receiver details are personal data. Do not export raw paths, PINs, cookies, URLs or credentials. Redacted diagnostics and bounded logs reduce exposure. Mesh trusted-LAN discovery is not cryptographic authentication. Host-only secrets and settings must not be exposed to guest pages. Sandboxing, permission checks and rate limits mitigate distinct threats.

Sources: docs/PORTAL_THREAT_MODEL.md; docs/MESH_SECURITY.md; docs/LINK_SANDBOX.md; #702

### Responsiveness and observability

*Bound the work, measure actual outcomes, preserve the UI.*

**Asynchronous design**

GTK callbacks must not block on network, disk or FFmpeg. Coalesce resize and progress updates; visual timers are active only during playback in a mapped window (playhead 500 ms, meters 100 ms). Device checks slow from four seconds while active to 30 seconds while idle. Preview generation and receiver generations discard late results.

**Reliability evidence**

Opt-in local summaries retain at most 100 records from 30 days. Confirmed PLAYING latency measures dispatch to first observed receiver PLAYING, not decoded first frame. Stall ratio uses observed PLAYING and BUFFERING intervals; unknown metrics stay null. A fake receiver benchmark uses repeated samples and runner-profile comparison, not physical TV claims.

**Errors and diagnosis**

Typed error catalogue, plain-language remediation and redacted details aim to make failures actionable. Use smoothcast --diagnostics; use --network-check only on an intentionally selected private receiver. Trace command IDs and actual status. Never infer a successful cast merely because a request was accepted; distinguish unverified checks from passed checks.

Sources: docs/RELIABILITY.md; docs/ERRORS.md; docs/ASYNC_WORKERS.md; docs/COMMAND_TRACING.md

### Installation, updates and canonical identity

*The version shown must describe the code that is actually running.*

**Source and package paths**

Canonical entry point sc.py prepares the isolated runtime, selects registered install, and activates one primary. Linux/macOS: python3 sc.py; Windows: py -3 sc.py. setup scripts handle platform dependencies. PyInstaller is the canonical native packager; wheel tests do not qualify GTK. Flatpak is experimental; offline x86_64 build evidence exists, native Debian/Fedora runtime remains pending (#263).

**Identity and refresh**

src/version.py is the single SemVer source. Running SHA and commit date are frozen at import. Display is vX.Y.Z - YYYY-MM-DD HHMM - Codename where metadata is available. A clean local develop checkout may refresh a Linux registered installation when quiescent, with forward ancestry and copied identity checks. A dirty checkout, unavailable platform refresh or active playback can defer update; never relabel old code as new.

**Managed updates and distribution**

Channel selection, read-only discovery, offline archive validation, staging and activation primitives are documented. Never mutate an active program generation; retain old generation and user data, verify staged content and health before activation. Native restart/MSI and end-to-end zero-interruption qualification remain open. MINOR/MAJOR owner-controlled; PATCH strongly preferred on develop without blocking valid unchanged-version shipments.

Sources: docs/UPDATE_ARCHITECTURE.md; docs/RELEASE_FLOW.md; docs/PACKAGING.md; docs/FLATPAK.md

### Operations and qualification

*A rigorous record of what has and has not been demonstrated.*

**Headless commands**

smoothcast --version reports canonical SemVer; --build-id adds source identity where known. --diagnostics provides local support information. --library-index scan ~/Videos and --library-index list --limit 50 inspect the private index. --demo provides isolated fake playback using generated media; it is not a real receiver qualification.

**Testing layers**

Use targeted Python tests, compileall, Ruff and mypy where applicable. Portable tests use fake receivers, synthetic media and loopback; GTK startup checks require the isolated Xvfb runner (scripts/test_gui_isolated.py). Never launch the user's real GUI or command their TV in routine tests. Version-history validation and non-force publication remain mandatory; develop testing may be deferred with an honest handover.

**Evidence and open scope**

The published platform matrix records 21 Nov 2026 CI at abffb94 across Linux, macOS and Windows; native desktop and real Cast checks were unverified there. Real receivers, browser/device compatibility, native installers, multi-node handoff and provider acquisition have distinct acceptance gates (#208/#209/#588). This manual is not a release certificate or a benchmark ranking.

Sources: docs/PLATFORM_STATUS.md; docs/DEVICE_COMPATIBILITY.md; docs/RELEASE_QUALIFICATION.md; docs/agents/testing.md

### Reference map and evidence record

*Use this manual as a guide; the pinned repository is the technical authority.*

**Product and UI**

README.md and docs/PRODUCT.md: product and feature overview. docs/VISION.md: future direction. docs/LAN_PORTAL.md, docs/WEB_TRANSFER_JOURNEY.md and docs/WEB_DESKTOP_PARITY.md: user journeys, routes, limits and gaps. docs/PICTURE_ADJUSTMENTS.md, docs/HDR_TONEMAP.md and docs/CHAPTER_NAVIGATION.md: media details.

**Architecture and operations**

docs/MESH_DESIGN.md, docs/MESH_PROTOCOL.md, docs/MESH_SEARCH.md and docs/MESH_SECURITY.md: membership, transport and sharing. docs/PORTAL_THREAT_MODEL.md and docs/LINK_SANDBOX.md: security. docs/INVARIANTS.md, docs/RELIABILITY.md, docs/ERRORS.md and docs/UPDATE_ARCHITECTURE.md: lifecycle and diagnosis. docs/api/openapi.json: exact API contract.

**Snapshot and provenance**

This edition expands the supplied v2.0.8 brochure (24 Nov 2026, c76ddfc71645) using develop v2.3.11, commit 38270735f2092089f58a34e1100d45923ac07410, 27 Nov 2026. Where documents conflict, current source and explicit implementation status take precedence; outstanding ticket acceptance is not assumed. Implemented means present; verified means a recorded check; qualified means the relevant native/physical scenario was tested.

Sources: github.com/gmanldn/smoothcast; CHANGELOG.md; docs/ISSUES.md
