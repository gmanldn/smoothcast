# Qualifying the link-acquisition sandbox (#588)

SmoothCast never trusts an arbitrary launcher's security policy. Point
`SMOOTHCAST_LINK_SANDBOX` at your absolute-path launcher
(`launcher EXECUTABLE ARGV...`), then attack-test it:

```sh
smoothcast --link-check --tools-only --qualify
```

The qualifier runs a tiny probe through the launcher and collects evidence
**host-side**: whether it reached a loopback service, a service on this
computer's private LAN address, a canary file in your home directory, and whether
a detached child process outlived the launcher (matched by tag, so PID
namespaces cannot hide or fake it). Nothing external is contacted. Results:

| check | passes when |
| --- | --- |
| `probe_ran` | the launcher really executed the probe |
| `loopback_denied` | zero connections reached the loopback listener |
| `private_lan_denied` | zero connections reached the LAN-address listener (`skipped` with no private address) |
| `home_denied` | the canary in `$HOME` was not readable |
| `process_tree_terminated` | no probe descendant survived |

The saved verdict (`~/.config/cast-control/link-qualification.json`) is bound
to the launcher's path, size and modification time: edit the launcher and it
must be re-qualified. `--qualify` exits non-zero unless every check passes.

Default behaviour is unchanged (an owner-configured launcher still enables a
provider). To make qualification mandatory, set
`SMOOTHCAST_LINK_REQUIRE_QUALIFIED=1`: providers then advertise only for a
launcher with a current passing verdict.

Not covered by this probe (still the launcher's job and your responsibility):
metadata/link-local and IPv6 egress, DNS rebinding and redirect handling,
disk/CPU/time quotas, and public-only egress. A launcher that denies *all*
network passes the probe but cannot download; a useful one must allow public
egress only. A reference `bwrap` invocation that satisfies the four checks is
exercised in `tests/test_link_sandbox_probe.py` (no network, blank home).
