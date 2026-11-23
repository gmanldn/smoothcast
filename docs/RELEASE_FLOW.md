# SmoothCast versions and owner-only main integration

**Normal development uses `develop` only.** No agent, automated test, updater
or GitHub Action merges, promotes or synchronises `main`. The project owner
alone decides when to integrate `develop` into `main`; there is no
automatic release PR or dependency on main's version or CI verdict.

## Day-to-day versioning

- Canonical source: `src/version.py`.
- Routine ticket work **never** changes `src/version.py`. Every development
  revision is uniquely identified by its Git commit SHA (headless
  `smoothcast --build-id`); semantic version numbers are *release intent*.
- Owner explicitly requests/version-bumps a release candidate when appropriate,
  then reviews and manually integrates it to `main`. Never auto-promote.
- Agents commit and fast-forward push quickly to `develop` without touching
  the version file. The history guard rejects regressions or skipped release
  numbers when a release bump does occur.
- Ticket closure is not the same as release creation.
- Source checkout, installed build and actively running Python process may
  report different versions. Do not describe a changed file as an activated
  update.

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
