# SmoothCast agent workflow — develop-only

**Authority:** [GitHub Issues](https://github.com/gmanldn/smoothcast/issues) and
[docs/ISSUES.md](../ISSUES.md). `develop` is the **only active development
branch**. `main` is owner-controlled archival/release integration: nobody and
no workflow automatically merges, promotes, creates a release PR or pushes
to `main`. The owner manually decides when (and whether) to merge it.

## Many agents, one trunk

1. `python3 scripts/ticket_digest.py --next --label agent-ready` or select
   a high-priority unclaimed P0/P1 issue; prioritise high-impact fixes, then
   older small independent tickets. Inspect the latest issue comments before
   touching code. Avoid claiming a ticket or file set another agent owns.
2. Claim with an issue assignment and **one short comment** identifying the
   intended file scope. Claims are advisory leases, not indefinite ownership:
   release when pushed or blocked. Split a large issue into clearly separate
   file-level slices so other agents can work concurrently.
3. Work in one independent detached worktree per task (never the user's
   checkout), stage **named files only**, and make small cohesive commits with
   `Refs #N`. No feature branches or agent PRs.
4. Push each finished coherent slice **directly to `origin/develop`**. If
   another agent pushed first, fetch and rebase only YOUR unpublished commits,
   reconcile overlapping code, and retry the fast-forward push. No `--force`,
   `reset --hard` of user changes, rewriting published history, or deleting
   other worktrees/stashes.
5. Report the exact SHA and any limitations in the issue. Close only when
   acceptance criteria have genuinely been demonstrated; a pushed commit alone
   is not proof of functionality. Release the claim before selecting the next
   independent issue.

```sh
git fetch origin develop
git worktree add --detach ../smoothcast-ISSUE origin/develop
cd ../smoothcast-ISSUE
# edit a bounded issue slice; stage exact files
git add path/to/changed.py
git commit -m 'fix: concise outcome (Refs #ISSUE)'
git fetch origin develop
git rebase origin/develop    # own unpublished commits only
git push origin HEAD:develop # fast-forward only; repeat fetch/rebase if contested
```

## Concurrency and token efficiency

- Never lock the entire repository for an agent or run a long task in the
  shared checkout. **Partition by file ownership and subsystem**, not by
  overlapping full-application refactors.
- Read the minimal relevant documentation and callers. Fetch current
  `develop` immediately before modifying shared configuration and version
  files; stale blob/HEAD rejection is a **refresh signal**, never force through.
- Prefer completing small independent tickets rather than keeping many broad
  tickets claimed. Push a minimal commit as soon as a useful self-contained
  change is ready; no artificial batches or waits for unrelated agents.
- The canonical `src/version.py` increments for a completed issue or an
  explicit owner version request. Re-read its current value just before the
  edit and never rewrite another agent's bump.
- Source/module manifests in `pyproject.toml` must remain coherent. When
  adding modules run `python3 scripts/ci/sync_pyproject.py` or make equivalent
  precise updates; do not clobber another agent's additions.

## Tests and CI by owner choice

Routine commits **do not wait for a test gate**. The Verify workflow is
manual (`workflow_dispatch`), and agents need not run tests before an owner-
requested rapid `develop` push. Do not silently disable runtime safety,
signature verification, data protection, singleton enforcement, or update
rollback to make this faster. Do not open the real GUI or control a TV during
automated work. If a change is untested, **state that explicitly** and do not
mark dependent safety-critical tickets as verified/closed.

The project retains tests and the manual Verify workflow for targeted or
full checks when the owner requests them. `main` is neither a test baseline
nor a gate on `develop` work.

## Main — manual owner action only

- No automatic `develop → main` pull request, merge, release promotion,
  tag publication or GitHub Actions writer to main.
- The owner alone may merge develop into main when desired. All agents,
  installers and CI automation must otherwise ignore main as a development
  dependency, including version and test-scope comparisons.
- Existing release-specific historical documentation or scripts may remain
  for manual maintenance; never invoke their main-mutating operations without
  the owner's explicit instruction.

**Never lose work:** preserve pending commits, user files, stashes and active
media sessions. If a conflict or broken install is uncertain, fail safely and
record the blocker rather than overwriting it.
