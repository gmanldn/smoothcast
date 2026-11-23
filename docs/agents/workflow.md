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

## Lazy, risk-weighted CI — never a develop merge gate

**Development never waits for CI.** Push coherent changes immediately to
`develop`; do not start long global pytest/GTK/native builds for every
agent patch. A failed or unrun check is *not* a licence to say a ticket passed
testing. Always describe actual evidence accurately.

| Event | Work scheduled | Purpose |
| --- | --- | --- |
| Ordinary `develop` push | No full Verify, native packaging or CodeQL | Eliminate redundant work from parallel agents |
| One nightly deferred run (after owner merges workflow into `main`) | Headless compile, Ruff and a compact security/reliability regression set on latest `develop` | Batch many commits into one bounded check; skip real GUI and native packaging |
| Security-sensitive portal/auth/room/transfer file push | Headless Portal Security suite only | Catch high-consequence auth/ownership regressions |
| Explicit Verify dispatch | Fast lane by default; full lane on MINOR/MAJOR | Owner-requested software qualification |
| Explicit Portal Security dispatch or PR into `develop` | Headless suite plus private Xvfb GTK smoke | Deeper qualification, without touching user desktop |
| Explicit Package dispatch or `v*` tag | Native Linux/macOS/Windows bundles | Avoid three-platform builds per edit |
| Weekly CodeQL schedule or manual dispatch | Static security analysis | Detect accumulated issues without per-commit scans |

- The nightly deferred workflow checks out **`develop` explicitly**, even though GitHub's cron uses the default branch's workflow definition. Its 15-minute budget and coalescing prevent runaway checks, and it never merges, pushes or tags anything.
- Portal push paths are intentionally narrow: cosmetic changes, general UI
  tweaks and most docs/tests should not trigger its heavy integration tests.
  Coalescing cancels obsolete security runs when a newer relevant revision
  arrives, so only the latest result matters.
- Individual agents may run small deterministic local or headless tests for
  risky code, but they are not a push prerequisite. Avoid re-running checks
  a different agent or successful containing run has already supplied.
- **Before an owner-requested manual `develop → main` promotion**, use
  GitHub Actions' **Run workflow** on `develop` for Verify and any relevant
  security/packaging workflows. Read actual run results; do not assume success
  from an older SHA. Manual `main` merging is always the owner's action.
- A scheduled GitHub workflow executes from the **default branch**; weekly
  CodeQL schedule modifications in `develop` only take effect after the
  owner merges that workflow to default `main`. Manual runs on `develop`
  use the current workflow immediately.

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
