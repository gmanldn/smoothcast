# SmoothCast versions and owner-only main integration

**Normal development uses `develop` only.** No agent, automated test, updater
or GitHub Action merges, promotes or synchronises `main`. The project owner
alone decides when to integrate `develop` into `main`; there is no
automatic release PR or dependency on main's version or CI verdict.

## Day-to-day versioning

- `src/version.py` is the **canonical release SemVer**. New versions are made in
  `develop` and merged there; no agent, test or CI promotes `main`.
- Every development slice is also identified by its Git SHA (`smoothcast
  --build-id`); `smoothcast --version` remains the semantic baseline.
- `agent.py ship` refreshes `origin/develop`, checks claims and version
  integrity, rebases only unpublished code and fast-forward pushes. It never
  automatically promotes a release or writes to main.
- Owner policy (26 Nov 2026): merging into `develop` and making new versions in
  `develop` are normal owner-directed release work. The legacy
  `ship --assign-patch` option is ignored; historical generated unpublished
  version-only commits remain recoverable.
- Source checkout, downloaded, installed and running processes can differ;
  changing a file on disk does not activate a running build.

## Commit display identity (critical canonical tracking)

Every pushed commit—patch release or ordinary commit—has a stable display
identity shown in the GTK header and next to the brand in the web room, screen and nodes pages:

```
vX.Y.Z - YYYY-MM-DD HHMM - Codename
```

- `vX.Y.Z` remains the SemVer in `src/version.py`; the badge never replaces it.
- `YYYY-MM-DD HHMM` is the commit's **committer date and time** in the timezone
  recorded in the commit object, never the server's or viewer's local clock.
  HHMM is zero-padded 24-hour time without a colon.
- `Codename` is a disposable two-weapon mnemonic from
  `src/commit_identity.py`: two names from the weapon-of-war tuple chosen by
  bytes of `sha256(full-lowercase-SHA)` (`64 * 64` combinations), joined by `-`.
- Both parts are derived from the exact commit, so they stay bound to it.
  Rebase, amend or cherry-pick creates a new commit and a new identity.
- The codename is only a memorable high-water cue for spotting a new commit; the
  committer date is the canonical marker, so the alias is disposable and may be
  redefined between releases.
- Reading is offline and bounded: loose and non-delta packed commit objects are
  parsed directly, with no Git subprocess, network, GUI or receiver work.
  Missing, malformed, oversized, delta-packed or unreadable provenance fails
  closed: show SemVer only, or SemVer plus the codename when only the date is
  unavailable. Never invent a date or word.
- Installed source copies carry the commit date and time in `src/.smoothcast-build`
  beside their SHA. Legacy date-only markers remain valid; no time is fabricated. Frozen distributions without embedded provenance report
  SemVer only; the Git SHA remains authoritative (`smoothcast --build-id`).

## Owner-controlled integration and publishing

1. Explicitly inspect and review the desired develop revision and reconcile
   any differences with main using the repository's protected-branch rules.
2. **Manually** merge/update `main` through an authorised owner action.
   Never bypass branch protection, force-push or enable automatic promotion.
3. If and only if the owner requests a published release, inspect and tag the
   intended main commit and invoke the separate Release SmoothCast workflow.
   Signing and native package/receiver qualification remain independent gates.

Historical helpers (`scripts/ci/promote_release.py`) are not scheduled by
the current Verify workflow. `sync-main.yml` is manual-dispatch only and
must not be triggered by agents unless explicitly requested.

For active agent coordination see [workflow](agents/workflow.md). For the
uncompleted P0 transactional updater see [#579](https://github.com/gmanldn/smoothcast/issues/579).
