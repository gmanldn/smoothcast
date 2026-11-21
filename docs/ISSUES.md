# SmoothCast issue tracker — authoritative development backlog

**Canonical work queue:** [SmoothCast GitHub Issues](https://github.com/gmanldn/smoothcast/issues).
This is the **only live backlog** for improvements, feature requests, bugs and
outstanding verification. Pull requests are code changes, not new backlog items.
There is intentionally **no root `IMPROVEMENTS.md`**.

## Fast agent path — bounded, read-only first

GitHub Issues stay authoritative. Do **not** download every issue body to
choose work.

1. `python3 scripts/ticket_digest.py --next` prints one highest-priority
   unclaimed issue. `--priority P0`, `--label`, `--limit` and `--search`
   narrow the output without fetching bodies.
2. Read **only that issue**:
   `gh issue view N --json number,title,state,labels,assignees,body,url`.
   Add `--comments` only when ownership or prior evidence matters.
3. Claim before editing: assign yourself and post one short comment
   (owner, intended scope, files). The assignee is the cheap machine-readable
   claim; the comment is the durable detail. An unassigned issue with comments
   may still be claimed—read them first.

   ```sh
   ISSUE=123
   gh issue edit "$ISSUE" --add-assignee @me
   gh issue comment "$ISSUE" --body "Claim: <agent> on develop; scope: <files>"
   ```
4. Use an isolated detached worktree of `origin/develop` and commit directly to
   `develop` (no issue branches). Do not modify or force-reset another checkout.
5. Validate targeted tests first, then the full headless suite when the change
   warrants it. Never launch or focus the real GTK app during routine tests.
6. Comment compact evidence and close when every software/CI item passes.
   Real-device checks are tracked in #208 and do not block closure.

Measured on 18 November 2026 with 113 open issues at that time:

| Query | Bytes |
| --- | --- |
| All open metadata (`number,title,labels,assignees,updatedAt,url`) | 36,144 |
| All open metadata plus bodies | 143,047 |
| `ticket_digest.py --limit 30` text | about 2,600 |
| One issue body (`--show N`) | about 1,200 |

These are byte/character counts, **not** provider-billed tokens. The digest
removes repeated metadata and bodies from agent context; it does not prove a
financial saving without an A/B usage measurement.

### Query budget

- Never request `body` (or comment bodies) for a list. Use the digest, then one
  `gh issue view` for the selected issue.
- Use `--json` plus explicit fields/`--jq`; do not dump raw issue JSON into a
  prompt. Summarise the fields the task needs.
- Keep full test logs on disk and summarise failures; preserve exact errors,
  commands, paths and uncertainty.
- If the digest is unavailable, a bounded GitHub search is cheaper than listing
  everything: `gh issue list --search 'is:open "[P0]" in:title' --limit 20`.

## Where work lives

| What | Location / rule |
| --- | --- |
| Unfinished improvements and bugs | [Open issues](https://github.com/gmanldn/smoothcast/issues?q=is%3Aissue+is%3Aopen) |
| All issues, including completed work | [Closed and open issues](https://github.com/gmanldn/smoothcast/issues?q=is%3Aissue) |
| Highest priority | Search the Issues tab for `is:issue is:open in:title "[P0]"` |
| Next priority | Search for `is:issue is:open in:title "[P1]"`, then `[P2]` |
| A specific migrated idea | Search the Issues tab for `SC-058`, substituting its original number |
| Changes awaiting review/merge | [Pull requests](https://github.com/gmanldn/smoothcast/pulls) targeting `develop` |
| Integration branch | `develop` is the only branch anyone commits to; `main` is **release-only** and updated by an automatic develop→main PR |
| Automated validation | [Verify SmoothCast actions](https://github.com/gmanldn/smoothcast/actions/workflows/verify.yml) |
| Current instructions for code agents | Root [AGENTS.md](../AGENTS.md), followed by this document |
| Historic original 50 ideas | [Verbatim snapshot](IMPROVEMENTS_ORIGINAL_50_20261118.md), **not** a current work queue |
| Migration and historical evidence | [18 November 2026 migration reference](ISSUES_MIGRATION_20261118.md) |

**Identifiers are separate:** `SC-058` is a *stable legacy proposal ID*,
not GitHub issue `#58`. For example, `SC-001` is
[issue #8](https://github.com/gmanldn/smoothcast/issues/8).
Always resolve via the issue title or GitHub search; do not assume the
issue number is the legacy number. The migrated range is `SC-001`–`SC-132`.

The stable title format is **`[P0][SC-058] Short action or outcome`** for
migrated work. Future proposals use informative titles, priority and scope;
choose new identifiers only deliberately (never reuse a legacy ID).

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
- **Open** means software work or tests remain. **Closed (completed)**
  requires automated evidence that the stated criteria are satisfied;
  real-device checks are tracked in #208, not required to close.
  **Closed (not planned/duplicate)** requires a clear reason and
  link to the superseding issue, if any. Never silently delete work.
- `IMPLEMENTED`, `CI PENDING`, `beta` and similar phrases in an old proposal
  are historical status notes, **not proof of final qualification**. For a
  nearly finished item, finish the missing runtime checks instead of
  rewriting functioning code.

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
   isolated GTK/Xvfb smoke, and optional physical receiver or OS testing
   (deferred device checks are tracked in #208).
5. **Provenance and links:** legacy `SC-nnn` when relevant; reference
   tests, dependent issues, PRs, logs, source commits and known limitations.
6. **Work-unit sizing:** use `Normalized units: 1` for one independently
   implementable, reviewable and validatable slice. Split before implementation
   when parts have separate owners, failure domains, rollback boundaries or
   validation environments. Dependencies do not justify bundling; use explicit
   `Depends on:` links. Coordination/epic issues are not implementation units.

New requests go straight to
[New issue](https://github.com/gmanldn/smoothcast/issues/new/choose),
using the provided template. Do not add a parallel Markdown feature list. If a
new request duplicates an issue, update/comment there and preserve any
additional requirements rather than creating competing tasks.

## Agent workflow: claim → implement → validate → close

1. Read `AGENTS.md`, this file and the specific issue **before editing**.
   Search for another owner, branch or open PR. Prefer P0 safety and high-value
   tasks, but don't collide with work someone else has claimed. Start with
   `scripts/ticket_digest.py`, not a full-backlog download.
2. **Claim the issue** by assigning yourself and posting one explicit comment
   (owner/agent, intended scope, likely touched files). If
   unable to finish, comment with blockers and handover steps. GitHub Issues
   records the durable state; ephemeral local notes do not.
3. Use an **isolated detached Git worktree** of `origin/develop` and commit to
   `develop` directly (see [workflow](agents/workflow.md)). Do not modify or
   force-reset a colleague's checkout; preserve stashes and uncommitted user
   work. Keep commits small and pushed frequently.
4. Implement the **smallest complete change**: production code, callers,
   error handling, cleanup, tests and docs. Avoid feature claims without a real
   protocol adapter. Refuse shortcuts that lose subtitle, track, seek, session
   or network-safety invariants.
5. Validate with headless, focus-safe commands:
   `python3 -m pytest -q tests` and
   `python3 -m compileall -q src scripts setup tests`. Ordinary CI must never
   launch the user's actual GTK window or send commands to their TV. GTK tests
   require the **explicit** isolated Xvfb runner
   `python3 scripts/test_gui_isolated.py`. Optional device checks use a
   separately authorised, controlled environment and are tracked in #208.
6. Push the tested commit to `develop` (`Refs #68`, never a PR for agents) and
   comment exactly which acceptance checks passed, which were not performed, and
   any backward-compatibility risks. Watch CI on `develop`; if it goes red, fix
   or `git revert` it before new work. Close by hand when automated evidence
   satisfies the criteria: GitHub closes them from `Fixes #N` only when code
   reaches `main`. Note any deferred device checks in #208.
7. Comment final evidence and close as **completed** once the specified
   software and CI criteria pass; record device checks in #208. Use a compact, parseable close comment:
   `Implementation: <SHA>`, `Why: <outcome>`, `Files: <paths>`,
   `Checklist: <pass/fail/pending per item>`,
   `Verification: portable=…; isolated GTK=…; device=…`.
   If superseded, close as duplicate/not planned with a link, not by deleting
   history. Reopen regressions rather than reintroducing a second backlog.

## Backlog maintenance and audit

- Sort/filter the live GitHub Issues list by priority and recent updates.
  Check claims and open PRs before planning a new batch.
- Periodically reconcile **issues, source code and CI**: merged code with
  green automated evidence is the completion signal; pending device checks
  belong in #208.
- Every proposal must remain discoverable in a GitHub issue or an explicitly
  linked, closed duplicate. Preserve paid research, original acceptance
  statements and provenance when splitting/merging tasks.
- The former source file is available in Git history, but **must not be
  recreated as a second canonical backlog**.
- For migration verification use the canonical IDs `SC-001` through
  `SC-132`; each must resolve to exactly one *open or completed* primary
  issue. See the [migration reference](ISSUES_MIGRATION_20261118.md) for the
  excluded duplicates and source revision.
- Tests such as `tests/test_backlog_regressions.py` protect playback safety
  and issue-workflow documentation instead of requiring a deleted Markdown
  backlog.

If GitHub Issues is temporarily unavailable, commit a repair or document the
blocker on a branch and reconcile it with the original issue when access
returns. Do not silently start a second permanent issue store.
