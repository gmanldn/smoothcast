# Agent efficiency — selective context and measurable cost

**First use the tiny built-in router**, which only processes the words passed
to it (no network calls, GUI startup or repository-wide reads):

```sh
python3 scripts/agent_context.py route src/cast_av.py subtitles
python3 scripts/agent_context.py list
python3 scripts/agent_context.py read architecture
```

`route` returns a small guide recommendation; `read` opens one topic and
refuses to print an oversized document rather than truncating important
instructions. Do not feed the complete historical archive back into every
session. [Handbook index](README.md) is the fallback for ambiguous tasks.

## Reliable token-saving practices

1. **Scope before reading.** Restate goal, affected files, constraints,
   acceptance checks. Find symbols and immediate callers, then read relevant
   file ranges. Avoid large recursive scans or opening full directories.
2. **Progressive disclosure.** Load root `AGENTS.md` (always), **one** topic
   document (when relevant), then specific sources. Open
   [archived notes](../AGENT_REFERENCE.md) only for historical edge cases.
   Do not add more long global agent instructions.
3. **Limit noisy command output.** Prefer `pytest -q`, bounded `git log`,
   `git diff --stat`, targeted `rg -n`, and `git show --format=short --stat`
   before full logs or diffs. Keep complete errors and test logs accessible;
   never discard causal context, exact stderr, source, security checks or data.
4. **Avoid unnecessary agent work.** Start with existing helpers and a
   focused test; don't spawn a separate agent for a tiny single-file task.
   Use specialised agents for substantial independent investigations with a
   narrow task, file scope and short evidence-backed report.
5. **Constrain changed code, not correctness.** Apply
   [Ponytail](../../.kilo/skills/ponytail/SKILL.md) to make the smallest
   complete diff, and [Caveman](../../.kilo/skills/caveman/SKILL.md) to
   report outcomes succinctly. Retain validation, tests, compatibility,
   protocol ownership and safety.
6. **Manage conversation context.** Start a fresh session for an unrelated
   task, compact a genuinely long ongoing session, and avoid swapping model
   settings repeatedly when prompt caching matters. These are optional
   agent-client behaviours, not SmoothCast runtime operations.

## Measurement, not estimated promises

Collect **per completed issue**: provider-billed input, output and cached
tokens; model/effort; number of tool calls; retries; CI status and
acceptance-result quality. Compare similar issues across two workflows.
A smaller file or a quieter log does not establish an equal percentage
reduction in total billed tokens. Avoid arbitrary context truncation and
do not claim savings without observed billing/quality data.

**Do not** add logging proxies, persistent token collectors, new app
dependencies, user credential routing or background telemetry by default.
Keep desktop tests headless per [testing](testing.md).

## Sources (retrieved 18 November 2026)

- [OpenAI: AGENTS.md guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md):
  concise root instructions, per-directory overrides and linked details.
- [OpenAI: Codex best practices](https://learn.chatgpt.com/docs/learn/best-practices):
  goal/context/constraints/done-when prompts, focused tasks, worktrees.
- [Anthropic: efficient Claude Code sessions](https://claude.com/resources/articles/maximizing-the-value-of-your-claude-code-sessions):
  quiet output, task boundaries, context checks and prompt-cache stability.
- [GitHub: optimise AI usage](https://docs.github.com/en/copilot/tutorials/optimize-ai-usage):
  limit irrelevant editor, chat and tool context; compact long tasks.
- [Anthropic: agent configuration](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more):
  separate always-on guidance from on-demand skills and subprocesses.
