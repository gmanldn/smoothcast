# SmoothCast LAN dashboard

When the SmoothCast desktop app is running, it starts a small web dashboard on
the selected private LAN IPv4 interface. The **LAN dashboard** card on the main
screen shows the address and a six-character PIN. Open that address in a
browser on the same local network and enter the PIN to view playback state and
use play/pause, stop, seek and volume controls. The queue is shown read-only.

The portal chooses a port by binding directly to an operating-system-assigned
ephemeral port. It does not check a port and bind later. It uses Python's
standard-library `http.server` module; no web framework, portal package or
additional runtime dependency is installed. The page, styles and scripts are
served locally with no external assets.

## Access and privacy

- A new unpredictable PIN is generated each time the portal starts or changes
  interfaces. The PIN uses six characters from an alphabet that omits easily
  confused letters and digits.
- After pairing, the browser receives a temporary, HTTP-only, same-site session
  cookie. Sessions expire after eight hours or when the portal stops. Reloading
  the page after expiry asks for the current PIN again.
- Five incorrect PIN attempts from one client are rate-limited. The PIN,
  session cookie and PIN-entry request are not written to SmoothCast logs.
- Every state-changing request checks the allowed Host and Origin and requires
  a per-session CSRF token. The portal exposes status, queue display, playback
  controls and an authenticated video upload. It has no file browser, arbitrary
  filesystem path or arbitrary URL cast.
- Uploads use sequential 2 MiB HTTP chunks with bounded 64 KiB server reads.
  Each acknowledged chunk is synced to disk; an interrupted chunk rolls back to
  its starting offset, and the browser resumes from the server's confirmed byte
  count. The browser never reads the entire video into memory.
- Uploads are staged in a mode-0700 cache directory with mode-0600 partial
  files. Only supported video suffixes are accepted, with at most three active
  uploads and a 512 MiB free-space reserve. Incomplete transfers are discarded
  when the portal stops and stale partials older than 24 hours are removed.
  Completed media files are retained because active/recoverable cast sessions
  may still read them.
- The dashboard reports transfer progress and supports cancellation. Only a
  fully received and size-checked staged file is passed to SmoothCast's normal
  cast path, which performs server-side media probing, transcoding and device
  streaming.
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
and CSRF checks, action validation, resumable staged uploads, HTTP responses,
and clean listener shutdown on loopback. They do not verify reachability from a
phone or another LAN host.
The isolated GUI smoke checks that the dashboard card builds; real second-device
and physical playback-control checks remain device qualification.
