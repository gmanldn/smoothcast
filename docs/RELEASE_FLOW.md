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
- The guarded `ship --assign-patch` allocator remains available only for
  explicit owner-authorised release intent. If a push races, it may remove
  only its own generated unpublished version-only commit before retrying.
  #583 tracks outstanding server-enforced exactly-once assignment.
- Source checkout, downloaded, installed and running processes can differ;
  changing a file on disk does not activate a running build.

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
