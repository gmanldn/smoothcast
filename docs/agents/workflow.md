# SmoothCast agent workflow — develop-only

**Authority:** [GitHub Issues](https://github.com/gmanldn/smoothcast/issues) and
[docs/ISSUES.md](../ISSUES.md). `develop` is the **only active development
branch**. `main` is owner-controlled archival/release integration: nobody and
no workflow automatically merges, promotes, creates a release PR or pushes
to `main`. The owner manually decides when (and whether) to merge it.

## Many agents, one trunk

1. Prefer `python3 scripts/agent.py start [ISSUE]` (auto-picks a free
   ticket if omitted). It refreshes develop, coordinates the claim, creates
   a private detached worktree, and writes a bounded source-grounded task
   brief in that worktree's Git admin directory. Or start with
   `python3 scripts/agent.py board` and `agent.py next`.
   These inspect live comment claims and hot files before choosing a P0/P1
   issue or small fix. Read current issue comments before changing code;
   `ticket_digest.py` alone cannot see every structured claim.
2. Claim using `python3 scripts/agent.py claim N --files src/file.py`
   (structured comment with a bounded TTL, not an assignee-only claim).
   Agents commonly share one GitHub user identity, so assignees and stale
   `in-flight` labels are **not** locks. The earliest active structured claim
   wins; on exit 3, choose another issue. The default lease is 90 minutes
   (configurable 30–180); renew only during real work with `agent.py heartbeat N`.
   Release via `agent.py progress N ... --release` or `agent.py release N`.
   Split large issues into separate file-level scopes for concurrency.
3. Work in one independent detached worktree per task (never the user's
   checkout), stage **named files only**, and make small cohesive commits with
   `Refs #N`. No feature branches or agent PRs.
4. Push each finished coherent slice **directly to `origin/develop`**.
   Preferred command in a private worktree: `python3 scripts/agent.py ship
   --message "concise change"` (auto-stages tracked changes, then targeted
   checks); add `--files` to stage new files. Explicit `--skip-checks`
   marks the slice unverified; the version-history check cannot be skipped.
   A successful ship records a SHA-based handover, including the next step.
   On push rejection, fetch and rebase only YOUR unpublished commits.
   Never force-push, reset away user changes, rewrite published history, or
   delete other agents' worktrees/stashes.
5. **Record permanent progress before relinquishing temporary ownership:**
   `python3 scripts/agent.py finish --done "landed…" --next "remaining…"
   --verification "actual tests"` saves a handover and releases the claim.
   Closure additionally needs `--next none --checklist "acceptance…" --close`.
   Legacy `progress`/`done` continue to work.
   `python3 scripts/agent.py progress N --done "landed ..." --next "remaining ..."
   --commit <actual-SHA> --verification "actual results" --release`. This
   posts searchable durable evidence and ends the lease; `agent.py next`
   previews the latest progress/handover for successors. On a partially
   complete issue, identify exactly which criteria remain. Close only when
   acceptance criteria have genuinely been demonstrated; a pushed commit alone
   is not proof of functionality. [Claim and handover protocol](../COORDINATION.md).

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
- `src/version.py` changes **only for explicit owner-authorised release
  intent**, not on ticket closure. Re-read before an authorised change. Use
  `smoothcast --build-id` to identify intermediate develop commits.
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
