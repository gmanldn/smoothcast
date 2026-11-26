# Qualifying the link-acquisition sandbox (#588)

SmoothCast never trusts an arbitrary launcher's security policy. Point
`SMOOTHCAST_LINK_SANDBOX` at your absolute-path launcher
(`launcher EXECUTABLE ARGV...`), then attack-test it:

```sh
smoothcast --link-check --tools-only --qualify
```

The qualifier runs a tiny probe through the launcher and collects evidence
**host-side**: whether it reached a loopback (IPv4) service, an IPv6 loopback
service, a service on this computer's private LAN address, the cloud metadata
address (`169.254.169.254`, link-local), a canary file in your home directory,
and whether a detached child process outlived the launcher (matched by tag, so PID
namespaces cannot hide or fake it). Nothing external is contacted. Results:

| check | passes when |
| --- | --- |
| `probe_ran` | the launcher really executed the probe |
| `loopback_denied` | zero connections reached the IPv4 loopback listener |
| `ipv6_denied` | zero connections reached the IPv6 `::1` listener (passes when the host has no IPv6 loopback) |
| `private_lan_denied` | zero connections reached the LAN-address listener (`skipped` with no private address) |
| `metadata_denied` | the probe could not reach the cloud metadata address `169.254.169.254` |
| `home_denied` | the canary in `$HOME` was not readable |
| `process_tree_terminated` | no probe descendant survived |

The saved verdict (`~/.config/cast-control/link-qualification.json`) is bound
to the launcher's path, size, modification time and SHA-256 digest: edit the
launcher and it must be re-qualified, even if its size and mtime are preserved.
On a system without a host process inventory, process-tree termination is
skipped rather than claimed verified. `--qualify` exits non-zero unless every check passes.

When a launcher is configured, `--link-check` also runs each installed engine
(`yt-dlp --version`, `aria2c --version`) **through** it and reports
`engines_via_launcher`. This catches a launcher that passes an isolation-only
probe but blocks or refuses the engine itself — for example the reference
launcher below refuses `aria2c`, so magnets cannot be acquired through it.

Default behaviour is unchanged (an owner-configured launcher still enables a
provider). To make qualification mandatory, set
`SMOOTHCAST_LINK_REQUIRE_QUALIFIED=1`: providers then advertise only for a
launcher with a current passing verdict.

## Reference launcher: public-only egress (Linux, YouTube)

`scripts/link_sandbox_bwrap.py` is a ready launcher built on bubblewrap
(`bwrap`) and `src/link_egress.py`:

```sh
export SMOOTHCAST_LINK_SANDBOX="$PWD/scripts/link_sandbox_wrapper"   # a one-line sh wrapper:
#   #!/bin/sh
#   exec python3 /path/to/scripts/link_sandbox_bwrap.py "$@"
smoothcast --link-check --tools-only --qualify
```

(`SMOOTHCAST_LINK_SANDBOX` must be an executable absolute path, hence the
wrapper.) The tool runs with an empty home and `/tmp`, write access only to
its staging directory, a private PID/IPC namespace that dies with the launcher,
and file-size and CPU limits. It has **no network at all** except HTTP(S)
through a filtering proxy on a private UNIX socket:

- only **public unicast** destinations: loopback, private, link-local (the
  169.254.169.254 metadata address), CGNAT, ULA, multicast, reserved,
  IPv4-mapped IPv6, NAT64, 6to4 and Teredo are refused, for IPv4 and IPv6;
- the proxy resolves names itself and requires **every** answer to be public
  (a mixed answer is a DNS-rebinding attempt), then connects to the checked
  IP, so a second lookup cannot swap the address;
- every connection is re-checked, so a redirect to an internal host fails;
- `CONNECT` to ports 80 and 443 only; at most 16 tunnels; per-tunnel byte,
  idle and total-time limits;
- no inbound port is opened and no router mapping is needed.

BitTorrent peers cannot be proxied, so this launcher refuses `aria2c`;
torrents need a different, torrent-capable launcher. Verified here: the
launcher passes `--qualify`, the tool cannot reach loopback, the LAN or the
internet directly, the proxy answers 403 for loopback, metadata, private and
IPv6 literals and for port 22, and a public site was reachable through it
(one manual `HEAD https://example.com`). Real YouTube downloads were not run.

## Not covered (still the launcher's and your responsibility)
the probe tests IPv4/IPv6 loopback, one private-LAN listener, the cloud metadata
address and a home canary, but not arbitrary private/link-local IPv6 ranges,
rebinding or redirects (`tests/test_link_egress.py` does, for the reference
proxy), nor disk quotas. A launcher that denies *all* network passes the probe
but cannot download.
