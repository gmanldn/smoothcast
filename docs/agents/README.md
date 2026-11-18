# Agent handbook — read by task, not in full

The root [AGENTS.md](../../AGENTS.md) is the **only always-read entry point**.
This is a routing page: open **only** the relevant child document.

| Task | Read |
| --- | --- |
| Claim, implement, review or close an issue | [Workflow](workflow.md) and [canonical issues](../ISSUES.md) |
| Test a change; debug GTK, CI, casting or local state | [Testing and safety](testing.md) |
| Find code owners; modify playback, devices, UI or setup | [Architecture](architecture.md) |
| Reduce context, tool output or code size | [Agent efficiency](efficiency.md), [Caveman](../../.kilo/skills/caveman/SKILL.md), [Ponytail](../../.kilo/skills/ponytail/SKILL.md) |
| Historical rationale, old invariants or regressions | [Full original notes](../AGENT_REFERENCE.md) — **historical; not policy** |

**Authority:** current code/tests and GitHub Issues for implementation and backlog;
root `AGENTS.md` for universal agent rules; these child docs for domain rules.
The original notes are preserved for reference, not loaded on every task.
If documents disagree, prefer current root, verified source, and issue
acceptance criteria; reconcile contradictions before changing behaviour.
