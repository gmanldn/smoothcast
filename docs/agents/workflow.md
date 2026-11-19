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
# ... edit, then run the checks below and commit ...
git fetch origin && git rebase origin/develop   # replays YOUR unpushed commits
python3 -m pytest -q tests                      # re-test after integrating
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
4. Add or adjust focused regression tests, then run the full headless checks.
   Never open the real GUI to test.
5. Commit small, coherent changes with a message that names the issue
   (`Refs #N`; GitHub closes issues only from the default branch, and an issue
   closes only when **all** acceptance criteria are supported, so close it by
   hand with evidence). Push when green.
6. Never equate CI success with hardware verification. Avoid deleting existing
   tickets or losing original research.

## Repo hygiene — commit checklist

- **Before every commit:** run `python3 -m pytest -q tests`,
  `python3 -m compileall -q src scripts setup tests` and
  `ruff check src scripts setup tests sc.py setup.py` (plus `mypy` if you touched
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
- **Mind the CI queue.** Verify runs one job per ref and a newer push cancels
  the pending run, so batch related commits into one push instead of pushing
  every small change.
- **No stray branches or worktrees.** Do not push topic branches. Remove your
  worktree after pushing. The prune workflow deletes any merged remote branch
  that slips through; do not leave stale ones.
- A local guard stops accidental commits on `main`
  (`scripts/ci/guard_branch.py`, wired into `.pre-commit-config.yaml`; install
  with `pip install pre-commit && pre-commit install`).

## Releases: develop → main automatically

1. On `develop`, once per release: `python3 scripts/ci/bump_version.py patch`
   (or `minor` / `major`), commit as `release: bump version to X.Y.Z`, push.
2. *Verify SmoothCast* runs on that push. Only if **every** job passes, the
   final `promote-release` job runs `scripts/ci/promote_release.py`, which
   promotes only when the version is strictly newer than `main`'s **and** merging
   into `main` yields exactly `develop`'s tree. Then it opens (or reuses) the
   develop→main PR and merges it with the head pinned to the verified commit,
   so code that was never verified, or that `develop` has already moved past,
   cannot reach `main`. If `main` holds content `develop` lacks, it refuses
   and fails loudly; merge `main` into `develop` to reconcile.
3. Merges made with the workflow token do not start new workflow runs, so
   `main` is not re-verified; its tree is identical to the verified `develop`
   commit by construction.
4. **Publishing** is separate and explicit. Dry-run *Release SmoothCast* from
   Actions (`tag=vX.Y.Z`, *publish* off: builds the sdist and wheel, installs
   the wheel headlessly, writes `SHA256SUMS` and notes, uploads them as a
   workflow artifact), then tag the release commit on `main`
   (`git tag vX.Y.Z && git push origin vX.Y.Z`). The workflow refuses a tag that
   disagrees with `src/version.py` or whose commit is not on `main`.
   Locally: `python3 scripts/ci/release_artifacts.py -h`.

Prerequisite (a repository setting, not code): *Settings → Actions → General →
Workflow permissions → "Allow GitHub Actions to create and approve pull
requests"* must be enabled, or `promote-release` fails at PR creation. Repo
auto-merge is not required.

CI success is not receiver, macOS or Windows qualification
([release qualification](../RELEASE_QUALIFICATION.md)).

**Identifier caveat:** `[P0][SC-058]` contains a legacy issue ID; `SC-058`
is **not** GitHub issue `#58`. Resolve the current GitHub issue by search.

**Protect the user's work:** don't discard dirty files, local commits, stashes,
or unmerged branches; never force-reset without explicit permission. A
diverged checkout requires backup/reconciliation, not `git reset --hard`.

**Merged-branch cleanup:** `.github/workflows/prune-merged-branches.yml`
prunes only merged same-repository source branches still at their recorded
head SHA and unused by open PRs; `scripts/ci/prune_merged_branches.py`
defaults to dry-run. The trusted `develop` workflow uses Git ref leases;
never delete active branches, worktrees, or protected refs.

**Version authority:** `src/version.py` only. Bump semantic versions at an
intentional release boundary, **not** for each commit. Distinguish loaded
runtime release, on-disk version and Git SHA in diagnostics.
`./smoothcast --version` is safe: it does not open GTK.

Use `git diff --stat` and targeted file ranges first. Avoid entire repository
or log dumps by default; preserve and surface exact failed traces when needed.
