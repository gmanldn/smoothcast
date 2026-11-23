# SmoothCast release updates and single-instance lifecycle

> **P0 lifecycle contract — #579 (23 November 2026).** Users have requested a
> continuously running managed installation, with rolling background staging
> from a selectable channel (default **develop**, alternative **main**).
> **Channel selection and read-only candidate discovery are implemented first.**
> Background *installation*, atomic generation switching, health acknowledgement
> and rollback are **not implemented yet**; do not advertise a zero-downtime
> updater until all of #579's acceptance gates are green.


Status: **S0 safety baseline plus P0 channel selection on `develop`**; no live source mutations. Transactional staged install, native restart and health acknowledgement are **not yet implemented**. Owner P0: #579; related #138 (update UI), #540 (stale GUI), #350 (source installations), #533 (Windows MSI), #426 (playback handoff). Reviewed 23 November 2026.

## Non-negotiable contracts

1. **Running ≠ installed ≠ downloaded ≠ available.** `src/version.py` reports the version imported by the running process. A file changed on disk does not replace loaded Python/GTK DLLs, and an upstream release check is never an installation.
2. **No silent Internet use.** Startup checks require the new explicit `check_release_updates=true` preference (off by default); the legacy persisted `auto_update` key is ignored. Signature checks use the new `release_check_verify=true` preference (on by default); legacy `verify_updates=false` is ignored. Preferences toggles apply on the next launch.
3. **Never hot-mutate the active generation.** No background `git pull`, `git merge`, `pip install`, MSI overwrite or automatic restart from GTK. Source updates use only checked metadata while the app runs. Already-playing media must continue without interruption.
4. **Immutable target.** The updater pins a candidate SHA from `refs/remotes/origin/main` or the corresponding `master` ref, not `FETCH_HEAD` after tag retrieval. It enforces fast-forward ancestry, a strictly increasing semantic release parsed without execution, bounded blob size and, by default, a signature verified with an explicitly trusted key. Frozen/installed apps must never source-update.
5. **One primary per user.** GTK GApplication performs normal session-bus activation. A failed activation does NOT authorise termination by a stale PID or a competing primary. Treat stale/unreachable primary as a recoverable user-visible error, not as proof of ownership. A secondary launch should check before dependency/bootstrap work. Forward media args to the existing primary when healthy.
6. **Privacy and rollback.** Settings, queues, history, user credentials and receiver identity live outside versioned program directories. Never upload them. The old verified program generation remains available until a replacement completes its health checks. A failed attempt leaves previous executable and user data intact.



### P0 offline generation staging (#580, first slice)

`setup/managed_generations.py:stage_local_snapshot` is an **offline primitive**.
Given a caller-authenticated manifest of relative paths, SHA-256 digests and
byte sizes plus an immutable commit ID, it writes a private new generation
under `releases/<commit>`. It enforces bounded file/total sizes, checks every
file digest, rejects symlinks, path escapes, special files and portable-case
collisions, and fsyncs content before publishing the final directory name.
A failed validation or disk write cleans up the private temporary generation.
It never reads or replaces `current`, `previous`, the user profile or
running Python/GTK modules.

**This does NOT yet fetch or authenticate manifests, construct a complete
independent native GTK/Python environment, atomically activate a generation,
or roll back a failed new primary.** Never call it automatically on an untrusted
Git checkout or present the staged directory as ready to launch. Those
remaining security and operational gates are tracked in #580–#582.

### P0 channel policy (#579, slice A)

The validated persisted `update_channel` setting is `develop` by default,
or `main` when explicitly selected in Preferences → Appearance → Updates.
Read-only checks fetch the exact selected remote ref and pin the candidate SHA,
report the selected channel, and never modify the running checkout. Develop
may report a changed commit even if the semantic version has not advanced.
Signature verification remains on by default, and check-on-startup remains
opt-in until an immutable, independently health-checked staging transaction
exists. Do not mistake the channel preference for automatic install consent.

**High-priority installer hazard:** the existing `setup/install_location.py`
`installed_sources` context manager renames and copies source directories at
the installed path. Its rollback protects from many setup failures but does
NOT guarantee uninterrupted running application code, nor safe concurrent
reinstall. **Do not invoke it as a live updater.** The P0 implementation must
introduce immutable fully staged releases, a stable launcher, separate venv
per generation, activation/rollback journal and exact new-generation health
acknowledgement before enabling background installation. Native MSI/package
installs follow their own signed installer mechanisms.

## Current S0 implementation (already on develop)

- `src/update_control.py:check_release`: opt-in, bounded read-only remote Git release check after the first UI frame. Dirty/non-release/diverged checkouts and frozen distributions are skipped. A candidate's immutable ref, version and signature are checked; **no working-tree files change**. `refresh_checkout(enabled=True)` remains a legacy **explicit** maintenance API, disabled by default and never called from the GUI.
- `src/cast_control.py`: background check is optional and daemonised, only reports on the GTK main loop. Re-activation and focus compare both the **on-disk semantic release** and the **local Git HEAD** with identities captured at process start. Same-version commits therefore still prompt a truthful one-time restart notice; the Git metadata reader is offline, bounded and never starts a Git subprocess. No hot reload and no forced playback stop.
- `setup/launch.py` and `smoothcast`: detect/activate the primary before expensive bootstrap. Do not kill from /proc PID-only scans if D-Bus fails; preserve the possibly active process and refuse a duplicate. Command-line media forwarding still goes through GApplication.
- Portable regression tests cover opt-out/legacy settings, signed and unsigned candidate checks in temporary Git repos, non-mutating checks, version parsing, dirty/diverged branches, unrelated fetched tags, singleton refusal, no PID-only termination and early activation. Full native GUI/receiver evidence is separate (#209/#208).

## Final architecture S1–S3 (not yet shipped)

### S1 — trusted discovery and review

A typed update state should distinguish `disabled`, `checking`, `not-eligible`, `up-to-date`, `available`, `untrusted`, `offline`, `failed`, `staged`, `restart-ready`, `installing` and `rolled-back`. Never return a false “up to date” when the network failed or the branch is ineligible.

An **Updates** page should show the running release, installed release, signed candidate and release notes, with explicit **Check now**, **Download & verify**, **Install after playback**, **Later** and diagnostic/cancellation states. A click must report exactly what it does. No startup network traffic without consent.

Candidate manifests: `{version, channel, platform, arch, commit, sha256, signing_identity, installer_kind, min_os, published_at}`. Validate every bound, channel, OS, architecture, signing identity and monotonic version. Acquire over HTTPS but **trust the signed digest**, not transport or release-note text.

### S2 — staged, transactional installer

Preferred native mechanism is **signed WiX/MSI** on Windows (#531–#538), notarised signed .app/update package on macOS (#216), Flatpak/OS package manager on Linux (#263), or the source-installer's own transaction (#350). Do not hand-roll a Windows directory swap behind MSI.

For source installs, use:
```
installation/launcher          # stable, owned entrypoint
installation/releases/<sha>/   # immutable full runtime with checksum manifest
installation/current           # proven atomic generation reference
installation/previous          # known-good rollback target
user-data/                     # never part of version switch
```
No two-step delete/recreate masquerading as atomic. Require disk space for two generations. Reject unsafe archive entries (absolute or `..` paths, escaping symlinks, duplicates/case collisions), invalid signatures, wrong architecture, missing native dependencies and untrusted install scripts. Stage privately, verify and run GUI-free health probes **before** touching the current generation.

State machine: `idle → checking → available → downloading → verified → staged → restart-ready → draining → installing → health-check → committed`; every stage supports a bounded, reasoned error and safe rollback. Persist a versioned, owner-only transaction journal atomically so duplicate clicks, crash/restart, stale lock and replay cannot apply twice.

**Drain is not an automatic stop.** If casting, wait until idle, request explicit restart, or use a proven receiver-preserving handoff (#426). Installer owns the per-user installation lease, waits for old primary exit, switches the generation using an OS-verified atomic operation, starts a private health probe and commits only after the exact new SHA acknowledges healthy startup. On failure, restore previous generation without touching user data.

### S3 — native singleton and stale-owner recovery

Linux: D-Bus primary plus an explicit health acknowledgement. Windows: per-user named mutex and authenticated same-user IPC; macOS: OS-native app activation plus equivalent acknowledgement. Require launcher identity across checkout, shortcut, packaged app and update generations. A successful D-Bus method call alone is not proof the window rendered.

A hung owner is **not safe to kill based on a timeout**. An explicit recovery action must inspect actual current-user owner, exact executable/script identity, process creation time and generation lease, rechecking before each termination and preserving stream helpers. Unknown or PID-reused identities fail closed. On crash, stale metadata is only a hint for verification, never a kill authorisation.

## Acceptance matrix

- **Read-only check:** no Git/network by default or under old persisted settings; no working-tree changes; no attempted Git/pip from frozen app; signature rejected; tag fetch cannot change selected SHA; downgrade, same version, diverged/dirty/dev checkout and malformed/oversized version rejected.
- **Transaction:** kill/power-loss injection at every download, verify, persist, generation switch and relaunch step; simulate disk full, missing permissions, shared lock, tampering, Unicode paths, duplicate requests, bad/expired signatures and rollback. Prove last good release and all user data survive.
- **Singleton:** simultaneous launches, D-Bus unavailable/hung, PID reuse, another user/checkout, missing or stale shortcut, abrupt primary crash, installed newer than running, active Cast. Never kill the wrong PID or start two primaries.
- **Qualification:** headless regressions on every appropriate CI lane; isolated Xvfb native GTK only where required; signed MSI A→B→repair→uninstall on Windows; macOS/Linux native launch; actual receivers under #208. Never claim an unsigned portable test qualifies the packaged release.

**Scope boundary:** Current S0 is a safety improvement, **not** a complete one-click update. #138 remains open for S1/S2; #540 remains open for S3 native recovery and acknowledgement. Any solution that reintroduces live Git pulls, implicit update consent or PID-only kills violates this document.
