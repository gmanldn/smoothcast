# Security policy

SmoothCast serves media to receivers on your local network and runs `ffmpeg`,
`catt` and a small HTTP server, so reports about local-network exposure, path
handling, subprocess ownership or untrusted-file parsing are welcome.

## Threat model: the trusted home LAN

SmoothCast is designed for a home network where everyone who has the Wi-Fi
password is trusted. It does **not** try to defend the household against people
on its own LAN; do not run it on shared office, dorm or public networks (or put
it on its own VLAN). Full rationale: [docs/VISION.md](docs/VISION.md#trust-model-the-trusted-home-lan).

In scope (please report):

- Anything that makes SmoothCast reachable from **outside** the LAN (public
  interfaces, port mapping, relays).
- Attacks by **web pages** in a LAN user's browser: CSRF, DNS rebinding,
  missing `Host`/`Origin` validation.
- Serving files **outside** configured library and upload roots (path
  traversal, symlink escape).
- Crashes or resource exhaustion from malformed input; unsafe subprocess
  argument handling; parsing bugs in untrusted media files.

Out of scope: a person on the home LAN controlling playback, the queue or rooms;
the absence of authentication between nodes or browsers on the LAN.

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting:
<https://github.com/gmanldn/smoothcast/security/advisories/new>
(repository **Security** tab → **Report a vulnerability**).

Include the SmoothCast version (`./smoothcast --version`), your OS, the steps to
reproduce and the impact. Attach a redacted `smoothcast --diagnostics` bundle
only if it does not contain private data. Never include real receiver IP
addresses, media paths or tokens you do not want disclosed.

You will get an acknowledgement as soon as the maintainer can respond; please
allow time for a fix before public disclosure.

## Supported versions

Only the latest release on `main` (see `src/version.py`) receives fixes.
