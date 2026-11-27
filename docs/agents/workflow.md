# SmoothCast agent workflow — develop-only

**Authority:** [GitHub Issues](https://github.com/gmanldn/smoothcast/issues) and
[docs/ISSUES.md](../ISSUES.md). `develop` is the **only active development
branch**. `main` is owner-controlled archival/release integration: nobody and
no workflow automatically merges, promotes, creates a release PR or pushes
to `main`. The owner manually decides when (and whether) to merge it.

## Choose the transport first (P0)

- Hosted ChatGPT containers: assume no native internet. Use the GitHub connector
  from the outset for reads, claims and guarded shipments per
  [sandbox networking](sandbox-network.md); do not try native clone/pull/push,
  gh, curl or downloads first.
- Network-enabled machines: use the native agent CLI below.
- Both preserve claim arbitration, SHA-pinned changes, non-force develop
  publication and truthful evidence. Connector progress automatically attempts the next PATCH and cannot close
  tickets; a standalone PATCH uses the
  [guarded release lane](sandbox-network.md#guarded-patch-release).

## Many agents, one trunk

1. Prefer `python3 scripts/agent.py start [ISSUE]` (auto-picks a free ticket if
   omitted). It refreshes develop, coordinates the claim, creates a private
   detached worktree and writes a bounded, source-grounded task brief there. Or
   inspect with `python3 scripts/agent.py board` and `agent.py next`, which check
   live claims and hot files before choosing a P0/P1 issue or small fix. Read
   current issue comments before editing; `ticket_digest.py` cannot see every claim.
2. Claim using `python3 scripts/agent.py claim N --files src/file.py`
   (structured comment with a bounded TTL, not an assignee-only claim).
   Agents often share one GitHub identity, so assignees and stale `in-flight`
   labels are **not** locks; the earliest active structured claim wins. On exit 3
   choose another issue. The lease defaults to 90 minutes (30–180); renew during
   real work with `agent.py heartbeat N` and release via `release N`. Split large
   issues into file-level scopes for concurrency.
3. Work in one independent detached worktree per task (never the user's
   checkout: edits there block launches), stage **named files only**, and make small cohesive commits with
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
   Legacy `progress N --done … --next … --commit SHA --verification … --release`
   still works: it posts the same durable evidence and ends the lease;
   `agent.py next`
   previews the latest progress/handover for successors. On a partially
   complete issue, identify exactly which criteria remain. Close only when
   acceptance criteria have genuinely been demonstrated; a pushed commit alone
   is not proof of functionality. [Claim and handover protocol](../COORDINATION.md).

**Preferred complete loop (claims, isolated worktrees, SHA identity and handover):**

```sh
python3 scripts/agent.py start              # auto-select or: start 584
cd /path/printed/by/start
# implement and review the narrow acceptance slice
python3 scripts/agent.py ship --message "fix: completed behaviour" --next none
# give real evidence; close only when every acceptance criterion passes
python3 scripts/agent.py finish --done "acceptance met" --next none --verification "actual checks" --checklist "criteria" --close
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
- Every `agent.py ship` has an immutable commit SHA; `src/version.py` is release
  SemVer. Owner policy (27 Nov 2026): **each nonempty shipment should increment PATCH in `develop`**, never
  `main`. Allocation failure alone does not block an unchanged valid version. MINOR and MAJOR remain owner-directed. The old `--assign-patch` flag is unnecessary. The version-history guard runs
  regardless of `--skip-checks`. If targeted checks already ran, use
  `--skip-checks` and record the evidence at finish; never claim unrun checks passed.
- Source/module manifests in `pyproject.toml` must remain coherent. When
  adding modules run `python3 scripts/ci/sync_pyproject.py` or make equivalent
  precise updates; do not clobber another agent's additions.

## Lazy, risk-weighted CI — never a develop merge gate

**Development never waits for CI or physical hardware qualification.** Push
coherent changes immediately to `develop`; do not start long global
pytest/GTK/native builds for every agent patch. Owner policy (27 Nov 2026):
hardware/device tests are desirable but never gate shipment to `develop`.
Record unrun hardware checks as UNVERIFIED; keep ticket acceptance and release
qualification separate from shipping. A failed or unrun check is *not* a licence to say a ticket passed
testing. Always describe actual evidence accurately.
**Finish, then move on:** ship, record it untested, and test lazily to close tickets.

| Event | Work scheduled | Purpose |
| --- | --- | --- |
| Ordinary `develop` push | No full Verify, native packaging or CodeQL | Eliminate redundant work from parallel agents |
| One nightly deferred run (after owner merges workflow into `main`) | Headless compile, Ruff and a compact security/reliability regression set on latest `develop` | Batch many commits into one bounded check; skip real GUI and native packaging |
| Security-sensitive portal/auth/room/transfer file push | Headless Portal Security suite only | Catch auth/ownership regressions |
| Explicit Verify dispatch | Fast lane by default; full lane on MINOR/MAJOR | Owner-requested qualification |
| Explicit Portal Security dispatch or PR into `develop` | Headless suite plus private Xvfb GTK smoke | Deeper qualification, no user desktop |
| Explicit Package dispatch or `v*` tag | Native Linux/macOS/Windows bundles | Avoid three-platform builds per edit |
| Weekly CodeQL schedule or manual dispatch | Static security analysis | Detect accumulated issues without per-commit scans |

- The nightly deferred workflow checks out **`develop` explicitly**, even though GitHub's cron uses the default branch's workflow definition. Its 15-minute budget and coalescing prevent runaway checks, and it never merges, pushes or tags anything.
- Portal push paths are intentionally narrow: cosmetic changes, general UI tweaks and most docs/tests do not trigger heavy integration tests. Obsolete security runs are cancelled when a newer revision arrives.
- Individual agents may run small deterministic local or headless tests for risky code, but they are not a push prerequisite. Avoid re-running checks a different agent has already supplied.
- **Before an owner-requested manual `develop → main` promotion**, use GitHub Actions' **Run workflow** on `develop` for Verify and security/packaging workflows. Read actual run results. Manual `main` merging is always the owner's action.
- A scheduled GitHub workflow executes from the **default branch**; weekly CodeQL schedule modifications in `develop` take effect after merging to `main`. Manual runs on `develop` use the current workflow immediately.

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
