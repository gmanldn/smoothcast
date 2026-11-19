# Security policy

SmoothCast serves media to receivers on your local network and runs `ffmpeg`,
`catt` and a small HTTP server, so reports about local-network exposure, path
handling, subprocess ownership or untrusted-file parsing are welcome.

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
