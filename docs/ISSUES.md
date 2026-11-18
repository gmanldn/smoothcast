# SmoothCast issue tracker — authoritative development backlog

**Canonical work queue:** [SmoothCast GitHub Issues](https://github.com/gmanldn/smoothcast/issues).
This is the **only live backlog** for improvements, feature requests, bugs and
outstanding verification. Pull requests are code changes, not new backlog items.
There is intentionally **no root `IMPROVEMENTS.md`**.

## Where work lives

| What | Location / rule |
| --- | --- |
| Unfinished improvements and bugs | [Open issues](https://github.com/gmanldn/smoothcast/issues?q=is%3Aissue+is%3Aopen) |
| All issues, including completed work | [Closed and open issues](https://github.com/gmanldn/smoothcast/issues?q=is%3Aissue) |
| Highest priority | Search the Issues tab for `is:issue is:open in:title "[P0]"` |
| Next priority | Search for `is:issue is:open in:title "[P1]"`, then `[P2]` |
| A specific migrated idea | Search the Issues tab for `SC-058`, substituting its original number |
| Changes awaiting review/merge | [Pull requests](https://github.com/gmanldn/smoothcast/pulls) |
| Automated validation | [Verify SmoothCast actions](https://github.com/gmanldn/smoothcast/actions/workflows/verify.yml) |
| Current instructions for code agents | Root [AGENTS.md](../AGENTS.md), followed by this document |
| Historic original 50 ideas | [Verbatim snapshot](IMPROVEMENTS_ORIGINAL_50_20261118.md), **not** a current work queue |

**Identifiers are separate:** `SC-058` is a *stable legacy proposal ID*,
not GitHub issue `#58`. For example, `SC-001` is
[issue #8](https://github.com/gmanldn/smoothcast/issues/8).
Always resolve via the issue title or GitHub search; do not assume the
issue number is the legacy number.

## Migration and evidence — 18 November 2026

- The prior `IMPROVEMENTS.md` contained **132 numbered proposals**:
  original compatibility/development proposals 1–50; later bug-and-reliability
  audit 51–100; and original player features recovered as 101–132.
- **All 132 have their own canonical GitHub issue**, with the stable
  `SC-001`–`SC-132` identifiers and the original acceptance requirement
  copied into the body. Items with prior implementation notes retain those
  notes; they remain open until any unverified acceptance work is completed.
- The migration source is an immutable
  [pre-deletion Git revision](https://github.com/gmanldn/smoothcast/blob/b76579c12f6a202188cc7964a0de06c09bd5aa9e/IMPROVEMENTS.md).
  The original 50-item player list (including *historical*, not revalidated
  completion marks) also survives verbatim under `docs/`.
- The migration generated two duplicate issues
  [#28](https://github.com/gmanldn/smoothcast/issues/28) and
  [#29](https://github.com/gmanldn/smoothcast/issues/29), both closed with
  a redirect to canonical [#26](https://github.com/gmanldn/smoothcast/issues/26)
  (`SC-019`) and [#27](https://github.com/gmanldn/smoothcast/issues/27)
  (`SC-020`). They are **not** additional backlog items.
- No uncommitted local material was included. If a paid research batch or
  user changes exist only in a local stash, backup or worktree, preserve
  them and create **new issues for genuinely new proposals**, referencing
  their provenance. Never overwrite or replace existing issues wholesale.

The stable title format is **`[P0][SC-058] Short action or outcome`**
for migrated work. Future proposals use informative titles, priority and
scope; choose new identifiers only deliberately (never reuse a legacy ID).

## Priorities, classification and status

- **P0:** correctness, broken playback, data/process safety, serious
  regressions, cross-device ownership or major unsupported receiver protocols.
  Start here when an item can be completed safely.
- **P1:** powerful functional improvements, compatibility edge cases,
  efficiency, AV accuracy, usability or maintainability.
- **P2:** refinements and optional capabilities with lower immediate impact.
- The migrated issues use `bug` for the 51–100 bug-audit group and
  `enhancement` for feature proposals and the recovered ideas.
  **Priority is encoded in the issue title**, because priority labels are
  not a prerequisite for the workflow. Do not infer priority from the
  GitHub issue number or the order issues were created.
- **Open** means work, tests or stated verification remains. **Closed
  (completed)** requires evidence that the stated acceptance criteria are
  satisfied. **Closed (not planned/duplicate)** requires a clear reason and
  link to the superseding issue, if any. Never silently delete work.
- `IMPLEMENTED`, `CI PENDING`, `beta` and similar phrases in the original
  proposal are historical status notes, **not proof of final qualification**.
  For a nearly finished item, finish the missing hardware/runtime checks
  instead of rewriting functioning code.

## Required issue content

Each improvement issue should contain:

1. **Outcome and scope:** what problem is solved, for which user, source,
   file, receiver or platform. Avoid a vague suggestion with no acceptance test.
2. **Reproduction / existing behaviour:** for bugs, a deterministic reproducer
   and observed vs expected behaviour; for features, relevant constraints and
   existing code that must not be duplicated.
3. **Acceptance checklist:** measurable normal, failure, boundary and
   security paths, including ownership during asynchronous playback.
4. **Verification class:** distinguish portable unit/integration CI,
   isolated GTK/Xvfb smoke, and actual physical receiver or OS testing.
5. **Provenance and links:** legacy `SC-nnn` when relevant; reference
   tests, dependent issues, PRs, logs, source commits and known limitations.

New requests go straight to
[New issue](https://github.com/gmanldn/smoothcast/issues/new/choose),
using the provided improvement template when applicable. Do not add a parallel
Markdown feature list. If a new request duplicates an issue, update/comment
there and preserve any additional requirements rather than creating
competing tasks.

## Agent workflow: claim → implement → validate → close

1. Read `AGENTS.md`, this file and the specific issue **before editing**.
   Search for another owner, branch or open PR. Prefer P0 safety and high-value
   tasks, but don't collide with work someone else has claimed.
2. **Claim the issue** with an explicit issue comment (owner/agent, intended
   scope, likely touched files, working branch). If unable to finish,
   comment with blockers and handover steps. GitHub Issues records the
   durable state; ephemeral local notes do not.
3. Use an **isolated Git worktree and issue-specific branch**. Do not
   modify or force-reset a colleague's checkout; preserve stashes and
   uncommitted user work. Keep commits small and pushed frequently.
4. Implement the **smallest complete change**: production code, callers,
   error handling, cleanup, tests and docs. Avoid feature claims without
   a real protocol adapter. Refuse shortcuts that lose subtitle, track,
   seek, session or network-safety invariants.
5. Validate with headless, focus-safe commands:
   `python3 -m pytest -q tests` and
   `python3 -m compileall -q src scripts setup tests`. Ordinary CI must
   never launch the user's actual GTK window or send commands to their TV.
   GTK tests require the **explicit** isolated Xvfb runner
   `python3 scripts/test_gui_isolated.py`. Hardware/device checks require
   a separately authorised, controlled test environment.
6. Open a PR referencing the issue (e.g. `Fixes #68`) and explain
   exactly which acceptance checks passed, which were not performed, and
   any backward-compatibility risks. Watch CI, fix failures and merge safely.
   If hardware qualification remains pending, say `Refs #68` rather than
   `Fixes #68` and **leave the issue open**.
7. Comment final evidence and close as **completed** only once all specified
   acceptance criteria pass. If superseded, close as duplicate/not planned
   with a link, not by deleting history. Reopen regressions rather than
   reintroducing a second backlog.

## Backlog maintenance and audit

- Sort/filter the live GitHub Issues list by priority and recent updates.
  Check claims and open PRs before planning a new batch.
- Periodically reconcile **issues, source code and CI**: being merged does
  not automatically mean finished if device qualification remains open.
- Every proposal must remain discoverable in a GitHub issue or an explicitly
  linked, closed duplicate. Preserve the user's paid research, original
  acceptance statements and provenance when splitting/merging tasks.
- The former source file is available in Git history, but **must not be
  recreated as a second canonical backlog**.
- For migration verification use the canonical IDs `SC-001` through
  `SC-132`; each must resolve to exactly one *open or completed* primary
  issue. The closed migration duplicates #28/#29 are excluded.
- Tests such as `tests/test_backlog_regressions.py` continue to protect
  playback safety and should check issue-workflow documentation instead of
  requiring the deleted Markdown backlog.

If GitHub Issues is temporarily unavailable, commit a repair or document the
blocker on a branch and reconcile it with the original issue when access
returns. Do not silently start a second permanent issue store.
