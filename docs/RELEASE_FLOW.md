# SmoothCast versions and owner-only main integration

**Normal development uses `develop` only.** No agent, automated test, updater
or GitHub Action merges, promotes or synchronises `main`. The project owner
alone decides when to integrate `develop` into `main`; there is no
automatic release PR or dependency on main's version or CI verdict.

## Day-to-day versioning

- Canonical source: `src/version.py`.
- Each coherent private-worktree `agent.py ship` allocates the next **PATCH**
  number on the newest `origin/develop` and appends an isolated version-only
  commit to the change. A losing parallel push discards only that generated,
  **unpublished** version commit, rebases its code, reallocates and retries a
  normal fast-forward push; nothing rewrites already-published commits.
- A successful develop push and its PATCH are **development identifiers**, not
  an automatic publication. The Git SHA (`smoothcast --build-id`) remains
  authoritative for exact source identity, including intermediate commits.
- Explicit valid existing SemVer bumps are not incremented a second time.
  `scripts/ci/check_version_history.py` rejects jumps and regressions.
  Raw `git push` bypasses the local allocator: prefer `agent.py ship`. The
  stronger server-enforced exactly-once **per-ticket** requirement is still
  tracked by #583, not falsely claimed as complete.
- The owner exclusively decides when to merge `develop` to `main`, tag or
  publish a release. Ticket closure is distinct from release publication.
- Source checkout, installed build and running process may show different
  versions; don't describe a changed file as an activated update.

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
