# Multi-agent claims and handovers (SmoothCast)

**Authority:** GitHub Issues for work/evidence; `develop` for shipped code. Claims are **short-lived advisory leases**, not permanent assignments, proof of progress, or reason to discard previously shipped work. This protocol coordinates agents; it is not a distributed database transaction. See [workflow](workflow.md).

## Default loop — one bounded slice

1. `python3 scripts/agent.py board` for currently live leases and hot files; `python3 scripts/agent.py next --limit 5` for candidates. **Do not use `ticket_digest.py --next` as a lock oracle**: its assignee/label metadata is useful for triage, but does not know whether an issue-comment lease expired.
2. Before editing, inspect the selected issue, relevant recent **comments**, its acceptance checklist and shipped commits (`Refs #N`). Check `develop` for existing implementation. A past agent's `Progress:` or `Implementation:` is evidence to assess, not an instruction to rewrite the same code or an automatic claim of completeness.
3. Claim **one independently shippable slice** using `python3 scripts/agent.py claim N --files src/x.py,src/y.py`. Default TTL: **90 minutes** (bounded **30–180**). If it reports a conflict (exit 3), choose a different scope or ticket. Claims carry an agent ID, touched paths, issue, timestamp, TTL and a GitHub comment ID. Other active claims on that issue or overlapping files take precedence by comment publication order; unrelated slices proceed.
4. Use a private detached worktree based on `origin/develop`. Push coherent commits directly to `develop` (no agent feature branches, PRs or main writes). Include `Refs #N`. Only rebase **your own unpublished commits**. No force pushes, destructive checkout cleanup or changes to a colleague's working tree.
5. After **each shipped slice**, record what actually landed, the commit SHA, exact verification run or not run, and any remaining acceptance items. Use `python3 scripts/agent.py progress N --done "..." --next "..." --commit <SHA> --verification "..."`. `--next "none"` is appropriate only if no software work remains. Record partial or unshipped work explicitly, never present it as merged.
6. Release promptly: `python3 scripts/agent.py release N --note "handover in preceding progress comment"`. A successful completed ticket can use `agent.py done N --why "..." --checklist "..." --verification "..." [--close]` to publish evidence and release; `--close` is ONLY for satisfied acceptance criteria. Never silently let a lease sit indefinitely. If interrupted, expiry permits another agent to take over; handover comments persist.

## Lease semantics

- `agent.py claim` adds a structured `<!-- sc-claim v1 ... -->` marker to an issue comment and checks for an earlier, live conflict. `agent.py heartbeat N` renews **only your still-live lease**; use sparingly if actual work continues. `agent.py release N` posts `<!-- sc-release v1 ... -->`, ending that agent's lease.
- The active lock is the **unexpired structured issue-comment claim**, not an assignee or `in-flight` label. These metadata fields can be stale after a crash; do not interpret them as permanent ownership. Legacy free-text `Claim:` notes have a conservative **45-minute** compatibility TTL. Do not delete another agent's comments or override an active conflicting lease.
- An expired claim may be replaced after checking the current issue comments and `develop`; expiry **does not revert commits, undo progress, remove history or invalidate a legitimate outstanding blocker**. Refresh the latest information before deciding what remains.
- Scope-specific claims are coordination hints, not a licence to edit overlapping source without checking. When the set of files grows, re-evaluate collisions before modifying new paths. The claim helper's optimistic race check is best-effort on GitHub comment visibility; under uncertain API failures, fail closed and re-read the issue.
- `board` and `next` read recent comment events and show live leases. `next` additionally surfaces the latest bounded progress/handover snippet for shortlisted issues. Fetch the chosen issue's full comments for all details rather than trusting a truncated preview.

## Durable handover format

Prefer the helper so agents can recognise the same fields:

```text
Progress: <one line describing code/diagnostics already completed>
Handover: <specific remaining acceptance items and next action>
Commit: <full SHA or 'not pushed'>
Verification: <actual command/result, or 'not run (unverified)'>
Files: <paths touched>
```

Link test evidence or other issues where it lives. Identify partial work, failing tests, unresolved conflicts, deferred device checks (#208), and any assumptions or decisions that future agents must not repeat. An issue stays open when checks are incomplete, regardless of whether the claim expired.

## Efficient follow-up

A successor first reads the latest durable `Progress:`, `Handover:`, `Implementation:` and release comments, then uses `git log --grep='#N'` and a narrowly scoped source/test inspection to verify what landed. Complete only the missing work. Reuse an existing valid test or design, do not re-propose it merely because the prior agent's lease ended. If an issue has been fully satisfied and evidenced, close it rather than opening another implementation task.

Claims shorten the **coordination horizon**; issue history preserves the **knowledge horizon**.
