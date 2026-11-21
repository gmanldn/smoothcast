# What makes SmoothCast different

SmoothCast aims to be the tool you reach for to **play media on every screen in
the house and let everyone in the room take part**. This page states the
promise, the guarantees behind it and the honest limits today.

## The promise

1. **Everyone participates, nobody installs.** A guest scans a QR code, types a
   PIN and can add music or films from their own phone, vote, reorder the queue
   and control playback.
2. **Every device is a target.** Chromecast, DLNA TVs and any browser (as a
   *screen* or *speaker*) appear in the same flow. Pick media, pick a target,
   play.
3. **Host or client.** One computer holds the media and runs the app (the
   **host**); every other device only needs a browser. More than one host can
   share a network.
4. **It does not break.** Playback is owned by one party at a time, commands are
   sequenced and idempotent, and a misbehaving phone, screen or receiver cannot
   interrupt what is playing.
5. **It stays yours.** No account, no cloud, no tracking. Access is a PIN on
   your own network and can be revoked per guest at any time.

## Roles

| Role | Needs | Can do |
| --- | --- | --- |
| **Host** (desktop app) | The media, GTK app, FFmpeg | Owns the queue and receivers; casts to Chromecast/DLNA; serves media to screens; hosts the room |
| **Controller** (guest browser) | A browser and the PIN | Add/upload media, vote, reorder, play, pause, seek, volume |
| **Screen / speaker** (any browser) | A browser, the PIN, one tap | Plays the shared queue on itself, direct or host-converted |
| **Cast / DLNA target** | A compatible TV or speaker | Plays what the host sends |

A device can be several of these at once: a phone is a controller and, if its
owner wants to listen privately, also a speaker.

## Guarantees (and where they are tested)

- **Fenced control.** Mutations carry revision and command IDs; stale or
  replayed requests are rejected (`tests/test_portal_commands.py`).
- **Isolation.** A screen is an independent target; commanding it never touches
  the host's Cast/DLNA session (`tests/test_portal_screens_http.py`).
- **Bounded everything.** Screens, streams, conversions, uploads, sessions and
  queues have hard caps and expiry (`tests/test_portal_screens.py`).
- **Clean teardown.** Conversion processes die with their connection; revoked
  guests lose their screens and media access at once.
- **Honest errors.** When something cannot work (unsupported format, no FFmpeg,
  receiver busy, screens disabled) the user sees why.

## Honest limits today

- The room is plain HTTP on a trusted LAN; trusted HTTPS is tracked in #340.
- Screens are driven from the room; the host's output dropdown does not yet list
  screens as a Cast-style receiver (#356) and screens do not synchronise with
  each other (multi-room sync is future work).
- Real-device and browser qualification is tracked in #208. Automated checks
  use loopback listeners, synthetic media and fake receivers.
- A browser can only play what it can decode; conversion needs FFmpeg on the
  host and is software-only, so very high bitrates can stress a small host.

## Roadmap pointers

Pairing and scoped trust between full nodes (#358), shared host libraries
(#349), node-to-node transfers (#357), a headless host without a window (#213)
and an event-push room channel (#316).
