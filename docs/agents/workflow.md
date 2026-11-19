# Agent workflow — tickets, code, releases

**Source of truth:** [docs/ISSUES.md](../ISSUES.md) and
[GitHub Issues](https://github.com/gmanldn/smoothcast/issues).
The retired root `IMPROVEMENTS.md` is **not** an active backlog.

## Branch model

- `develop` is the integration branch: every issue branch and pull request
  targets `develop`.
- `main` is **protected** and release-only. It receives release merges from
  `develop`; never push to it directly and never open a feature PR against it.
- `src/version.py` is bumped on `develop` at a release boundary; promoting
  `develop` into `main` publishes that release.

1. Read the relevant GitHub issue and its acceptance criteria first; check
   related PRs, existing implementation and relevant logs. Prioritise P0/P1.
2. **claim the issue** in a comment before work; avoid duplicating another
   agent's active task. Use an isolated branch/worktree off `develop`, never
   the shared checkout.
3. Locate the changed symbols, callers and tests. Choose a minimal **complete**
   fix; reuse helpers and standard library where sensible. Preserve validation,
   casting ownership, accessibility, existing behaviour and diagnostics.
4. Add/adjust focused regression tests, run relevant headless tests, then
   full headless verification where feasible. Never open the real GUI to test.
5. Commit and push coherent changes frequently; link the issue and PR with
   tests run, evidence, limitations and outstanding real-device validation.
6. Only close a ticket when **all** acceptance criteria are supported, including
   TV/platform tests when required. Never equate CI success with hardware
   verification. Avoid deleting existing tickets or losing original research.

## Tagged releases (#257)

1. Bump `src/version.py` on `develop` once, at the release boundary; merge
   `develop` into protected `main` through the normal release merge.
2. **Dry run first:** Actions → *Release SmoothCast* → Run workflow with
   `tag=vX.Y.Z` and *publish* off. It verifies the tag equals `src/version.py`,
   builds the sdist and wheel, installs the wheel headlessly, writes
   `SHA256SUMS` and notes, and uploads them as a workflow artifact only.
3. Tag the release commit on `main` (`git tag vX.Y.Z && git push origin vX.Y.Z`).
   The workflow refuses a tag that disagrees with `src/version.py` or whose
   commit is not on `main`, then publishes a GitHub release with the artifacts,
   checksums and notes. Locally: `python3 scripts/ci/release_artifacts.py -h`.

CI success is not receiver, macOS or Windows qualification
([release qualification](../RELEASE_QUALIFICATION.md)).

## Worktrees and repo hygiene

Never edit in the shared checkout. Every issue gets its **own worktree and
branch**, created from a fresh `origin/develop`, so parallel agents cannot
overwrite each other's files, stashes or index:

```sh
git fetch origin
git worktree add ../smoothcast-N -b fix/N-short-slug origin/develop
cd ../smoothcast-N          # work, test and commit only here
```

- **Naming:** `fix/N-slug`, `feat/N-slug` or `docs/N-slug`, one issue per
  branch; `N` is the GitHub issue number. Never reuse a branch name.
- **Before you start:** `git worktree list` and `git branch -r` — if another
  branch or open PR already covers the issue, join it instead of duplicating.
- **Before every commit:** `git status` and `git diff --stat` show only files
  you meant to change. Never commit `__pycache__`, logs, caches, scratch or
  generated files, credentials or `.env`; stage files by name, not `git add -A`
  in a dirty tree.
- **Commit and push small, coherent changes.** Run
  `python3 -m pytest -q tests`, `python3 -m compileall -q src scripts setup tests`
  and `ruff check src scripts setup tests sc.py setup.py` first (and `mypy` if
  you touched a gated module).
- **Sync by merging, never by rewriting:** `git fetch origin` then
  `git merge origin/develop`. No rebase, amend or force-push on a pushed or
  shared branch, and no `git reset --hard` on work you have not backed up.
- **Mind the CI queue.** Verify runs one job per ref; a newer push cancels the
  pending run. Batch related commits and push once instead of pushing every
  small change, or no full run ever completes.
- **After merge, clean up your own work:** `git worktree remove ../smoothcast-N`
  and `git branch -d fix/N-slug`. Squash merges leave the source branch behind;
  the prune workflow removes merged remote branches, so do not leave stale
  ones, and never delete another agent's worktree, branch or stash.
- **Do not take over a claimed issue.** Check assignees and comments, claim
  before editing, and release the claim with a comment if you stop.

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
