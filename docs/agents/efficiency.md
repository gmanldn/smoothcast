# Agent efficiency — selective retrieval

The root [AGENTS.md](../../AGENTS.md) contains universal rules only. Read
[the handbook index](README.md) and **one** relevant topic document before
reading historical material. Do not load all of `docs/AGENT_REFERENCE.md`
into each agent session.

- **Caveman:** concise answer, accurate commands and evidence, no repeated
  narrative; see [skill](../../.kilo/skills/caveman/SKILL.md).
- **Ponytail:** smallest *complete* change, reuse-first, all required tests
  and safety intact; see [skill](../../.kilo/skills/ponytail/SKILL.md).
- Search the task's symbols, then read source ranges and direct callers.
- Summarise passing tests. For failures, preserve stack traces, logs and
  needed reproduction details. Never truncate code or safety conditions.
- Prefer `git diff --stat`, focused diffs and links to large source output.
- Keep optional agent proxies and telemetry out of the SmoothCast runtime.
  Review external installations/credential routing separately.

See [the measurements and optional upstream tooling](../AGENT_TOKEN_EFFICIENCY.md).
Instruction character counts are not measured billed-token savings; compare
input/output/cached provider tokens **per successful task**, including retries.
