# SmoothCast versions and owner-only main integration

**Normal development uses `develop` only.** No agent, automated test, updater
or GitHub Action merges, promotes or synchronises `main`. The project owner
alone decides when to integrate `develop` into `main`; there is no
automatic release PR or dependency on main's version or CI verdict.

## Day-to-day versioning

- `src/version.py` is the **canonical release SemVer**, not a counter of
  commits or completed tickets. Normal agent shipments do not edit it.
- Every development slice is identified by its Git SHA (`smoothcast
  --build-id`). `smoothcast --version` remains the semantic baseline.
- `agent.py ship` refreshes `origin/develop`, checks claims and version
  integrity, rebases only unpublished code and fast-forward pushes. It never
  automatically promotes a release or writes to main.
- Owner policy (25 Nov 2026): no per-ticket PATCH allocation. Closing a ticket
  never requires a new SemVer. The legacy `ship --assign-patch` option is
  ignored; release changes are separate explicit owner-directed commits.
  Historical generated unpublished version-only commits remain recoverable.
- Source checkout, downloaded, installed and running processes can differ;
  changing a file on disk does not activate a running build.

## Commit display identity (critical canonical tracking)

Every pushed commit—patch release or ordinary commit—has a stable display
identity shown next to the brand in the web room, screen and nodes pages:

```
vX.Y.Z - YYYY-MM-DD - Codename
```

- `vX.Y.Z` remains the SemVer in `src/version.py`; the badge never replaces it.
- `YYYY-MM-DD` is the commit's **committer date** in the timezone recorded in
  the commit object, never the server's or viewer's local date.
- `Codename` comes from the frozen 64-entry weapon-of-war tuple in
  `src/commit_identity.py`: `sha256(full-lowercase-SHA)[0] % 64`.
- Both parts are derived from the exact commit, so they stay bound to it.
  Rebase, amend or cherry-pick creates a new commit and a new identity.
- The tuple and index rule are frozen identity data: reordering, removing or
  adding a name would relabel already-published commits.
- Reading is offline and bounded: loose and non-delta packed commit objects are
  parsed directly, with no Git subprocess, network, GUI or receiver work.
  Missing, malformed, oversized, delta-packed or unreadable provenance fails
  closed: show SemVer only, or SemVer plus the codename when only the date is
  unavailable. Never invent a date or word.
- Installed source copies carry the commit date in `src/.smoothcast-build`
  beside their SHA. Frozen distributions without embedded provenance report
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
