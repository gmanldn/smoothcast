# SmoothCast release promotion — on-demand engineering procedure

Open this page when promoting, tagging or diagnosing a release. The routine
agent ticket workflow remains short in [workflow](agents/workflow.md).
Do not bypass protected `main` or report unpromoted `develop` versions
as releases. GitHub issue #518 tracks the administrator policy blocker.

## Releases: develop → main automatically

1. On `develop`, for each **completed GitHub ticket**, run
   `python3 scripts/ci/bump_version.py patch --issue N --expect X.Y.Z` after
   focused tests, and commit the bump with the ticket's code (`Refs #N`).
   Push fast-forward only. If another ticket bumped first, fetch/rebase, rerun
   with the new version and repeat validation. Never silently reuse a patch.
   MINOR/MAJOR bumps remain explicit release decisions.
2. *Verify SmoothCast* eventually validates the **latest `develop` head**
   (full matrix for any MINOR/MAJOR difference against `main`, fast lane
   for patch-only progress). Earlier queued revisions may be cancelled and
   must not be treated as tested. Only if **every scheduled** job passes, the
   final `promote-release` job runs `scripts/ci/promote_release.py`, which
   promotes only when the version is strictly newer than `main`'s **and** merging
   into `main` yields exactly `develop`'s tree. Then it opens (or reuses) the
   develop→main PR and merges it with the head pinned to the verified commit,
   so code that was never verified, or that `develop` has already moved past,
   cannot reach `main`. If `main` holds content `develop` lacks it refuses,
   naming the files. `sync-main.yml` merges `main` back into `develop` when
   `main` moves (writes only `develop`); a real conflict fails it with the
   files to resolve by hand (`git merge origin/main` in a worktree).
3. Workflow-token merges start no new runs; `main`'s tree equals the verified
   `develop` commit by construction.
4. **Publishing** is separate and explicit. **Dry run first:** run *Release SmoothCast* from
   Actions (`tag=vX.Y.Z`, *publish* off: builds the sdist and wheel, installs
   the wheel headlessly, writes `SHA256SUMS` and notes, uploads them as a
   workflow artifact), then tag the release commit on `main`
   (`git tag vX.Y.Z && git push origin vX.Y.Z`). The workflow refuses a tag that
   disagrees with `src/version.py` or whose commit is not on `main`.
   Locally: `python3 scripts/ci/release_artifacts.py -h`.

Prerequisite (repository setting): *Settings → Actions → General → Workflow
permissions → "Allow GitHub Actions to create and approve pull requests"*, or
`promote-release` fails at PR creation. Repo auto-merge is not required.

CI success is not receiver, macOS or Windows qualification
([release qualification](../RELEASE_QUALIFICATION.md)).

