---
description: Lease-aware SmoothCast issue picking, progress and handover
---

Use the canonical lease-aware agent workflow rather than treating an assignee
or stale `in-flight` label as a permanent lock.

1. `python3 scripts/agent.py board`; then `python3 scripts/agent.py next --limit 5`.
   Select the highest-value independent ticket, preferring P0/P1 and older small
   fixes. For a supplied issue number, inspect its GitHub body, comments, and
   shipped commits before changing anything. `ticket_digest.py` is for cheap
   metadata triage, not definitive lease ownership.
2. Claim one bounded slice: `python3 scripts/agent.py claim N --files src/x.py`.
   Default lease 90 minutes; heartbeat only if actively working. On conflict,
   do not override: choose another issue or path scope.
3. Work in an isolated detached worktree from `origin/develop`; stage named
   files, commit `Refs #N`, and push directly to `develop` (never an agent
   branch/PR or an automatic main promotion).
4. Record what landed and what remains using `python3 scripts/agent.py progress N
   --done "..." --next "..." --commit SHA --verification "..." --release`.
   If stopping without a commit, say so: the handover must remain useful after
   the lease expires. Do not claim tests that were not run or start a real GUI.
5. Close only with adequate evidence for all acceptance criteria. Future
   agents read the latest progress/handover and source history before rewriting.

[Canonical coordination](../../docs/COORDINATION.md) ·
[Issue policy](../../docs/ISSUES.md)
