# Agent workflow — tickets, code, releases

**Source of truth:** [docs/ISSUES.md](../ISSUES.md) and
[GitHub Issues](https://github.com/gmanldn/smoothcast/issues).
The retired root `IMPROVEMENTS.md` is **not** an active backlog.

## Branch model — `develop` is the only working branch

> **Everyone — humans and agents — commits to `develop`. Nobody commits or
> pushes to `main`.** There are no feature branches and agents do not open
> pull requests. `main` is release-only and is updated *automatically*.

- `develop` is trunk. Every change lands there as a small, tested commit.
- `main` holds released versions only. When a **verified** `develop` commit
  carries a newer `src/version.py` than `main`, the *Verify SmoothCast*
  workflow opens a develop→main pull request and merges it (see
  [Releases](#releases-develop--main-automatically)). Nothing else writes to `main`.
- `src/version.py` is the one release authority; bump it deliberately, once
  per release, with `python3 scripts/ci/bump_version.py` (default: patch).
- External contributors without push access may open a PR **against
  `develop`**; that is the only PR flow besides the automatic release PR.

## Daily flow (one task = one detached worktree)

Never edit in the shared checkout: parallel agents would overwrite each
other's files, index and stashes. A detached worktree gives each task an
isolated tree with no branch to leave behind:

```sh
git fetch origin
git worktree add --detach ../smoothcast-N origin/develop
cd ../smoothcast-N                       # work, test and commit only here
# ... edit, then run the fast lane below and commit ...
git fetch origin && git rebase origin/develop   # replays YOUR unpushed commits
# fast lane: compileall + ruff + mypy; full pytest only for MINOR/MAJOR
git push origin HEAD:develop                    # fast-forward only, never --force
cd .. && git worktree remove smoothcast-N       # clean up when pushed
```

If the push is rejected, someone else pushed first: `git fetch`, rebase your
unpushed commits again, re-test, push. Never force-push, and never rebase or
amend commits that are already on `origin`.

1. Read the relevant GitHub issue and its acceptance criteria first; check
   existing implementation and relevant logs. Prioritise P0/P1.
2. **Claim the issue** in a comment before work and avoid duplicating another
   agent's active task (check assignees and comments). Release the claim with
   a comment if you stop.
3. Locate the changed symbols, callers and tests. Choose a minimal **complete**
   fix; reuse helpers and standard library where sensible. Preserve validation,
   casting ownership, accessibility, existing behaviour and diagnostics.
4. Add or adjust focused regression tests and run them before committing.
   Patch work takes the fast lane; run the full suite only for a MINOR/MAJOR
   bump. CI applies the same lane policy. Never open the real GUI.
5. Commit small, coherent changes with a message that names the issue
   (`Refs #N`). Close by hand when code and automated CI satisfy the criteria;
   device checks are tracked in #208, not close gates. Push when green.
6. Avoid deleting existing tickets or losing original research.

### `pyproject.toml` module lists

After adding a `src/` module run `python3 scripts/ci/sync_pyproject.py`
(derives `py-modules`, sorts the mypy list, one entry per line). A rebase
conflict in those lists: run it, `git add pyproject.toml`, continue.

## Repo hygiene — commit checklist

- **Before every commit:** run focused tests covering changed behavior,
  `python3 -m compileall -q src scripts setup tests` and
  `ruff check src scripts setup tests smoothcast setup.py` (plus `mypy` if you touched
  a gated module). `git status` and `git diff --stat` must show only files you
  meant to change.
- **Stage files by name**, not `git add -A` in a dirty tree. Never commit
  `__pycache__`, logs, caches, scratch files, credentials or `.env`.
- **Integrate by rebasing only your own unpushed commits.** Never rewrite
  pushed history, never `git reset --hard` work you have not backed up, and
  never touch another agent's worktree, stash or claimed issue.
- **Keep `develop` green.** Trunk has no PR gate, so your local checks are the
  gate. If a push turns CI red, fixing it (or `git revert <sha>`) comes before
  new work, whoever caused it.
- **Continuous-push CI is coalesced (#539):** the Verify workflow
  permits **one running** run plus **the newest pending** run per Git ref.
  Old pending revisions are marked `cancelled` without running; the active run
  is *never interrupted*. The newest tested `develop` SHA includes all older
  commits. Use targeted local tests before each push and batch related commits.
  Do not treat a superseded/cancelled SHA as green, or close its issue merely
  because a newer run was queued. A confirmed failure on the current head
  still blocks further work until fixed.
- **Patch fast/full policy:** `develop` compares its version to the last
  released `main`, not the immediately prior push. This prevents a cancelled
  intermediate MINOR/MAJOR bump from silently losing the required full matrix.
  Patch-only progress stays fast; MINOR/MAJOR changes since `main` get all
  native, media and packaging contract checks.
- **CI events:** contributor PRs **into `develop`** still run Verify and
  relevant portal/package/CodeQL checks. The automated `develop → main`
  release PR does *not* duplicate them: the latest `develop` push is already
  verified at the exact commit. Package builds also run on packaging-relevant
  `develop` pushes and real release tags; CodeQL retains weekly scans.
- **No stray branches or worktrees.** Do not push topic branches. Remove your
  worktree after pushing. The prune workflow deletes any merged remote branch
  that slips through; do not leave stale ones.
- A local guard stops accidental commits on `main`
  (`scripts/ci/guard_branch.py`, wired into `.pre-commit-config.yaml`; install
  with `pip install pre-commit && pre-commit install`).

## Releases: develop → main automatically

1. On `develop`, once per release: `python3 scripts/ci/bump_version.py patch`
   (or `minor` / `major`), commit as `release: bump version to X.Y.Z`, push.
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

**Identifier caveat:** `[P0][SC-058]` contains a legacy issue ID; `SC-058`
is **not** GitHub issue `#58`. Resolve the current GitHub issue by search.

**Protect the user's work:** never discard dirty files, local commits, stashes
or unmerged branches, or force-reset without permission; reconcile a diverged
checkout, don't `git reset --hard`.

**Merged-branch cleanup:** `prune-merged-branches.yml` prunes only merged
same-repository branches still at their recorded head and unused by open PRs
(`scripts/ci/prune_merged_branches.py` defaults to dry-run). Never delete
active branches, worktrees or protected refs.

**Version authority:** `src/version.py` only. Bump semantic versions at an
intentional release boundary, **not** for each commit. Distinguish loaded
runtime release, on-disk version and Git SHA in diagnostics.
`./smoothcast --version` is safe: it does not open GTK.

Use `git diff --stat` and targeted file ranges first; avoid whole-repo or log
dumps, but keep exact failed traces.
