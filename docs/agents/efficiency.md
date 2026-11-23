# Agent efficiency — selective context and measurable cost

Compare **provider tokens** and billed cost before claiming a measured saving;
character-count reductions alone do not prove token efficiency.

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
3. **Limit noisy command output.** Prefer focused tests for changed behavior
   while iterating. Patches take the fast lane; run `pytest -q -n auto` only
   for MINOR/MAJOR bumps. CI applies the same lane policy. Also prefer bounded
   `git log`, `git diff --stat`, targeted `rg -n`, and
   `git show --format=short --stat` before full logs or diffs. Keep complete
   errors and test logs accessible; never discard causal context, exact
   stderr, source, security checks or data.
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

## Why the root file stays small

Gloaguen et al., ["Evaluating AGENTS.md"](https://arxiv.org/abs/2602.11988)
(arXiv 2602.11988), found repository context files generally did not raise task
success and added over 20% inference cost; repository overviews did not help,
while non-standard practices did. Anthropic recommends under 200 lines per
`CLAUDE.md`, concrete verifiable instructions, imports for sharing
`AGENTS.md`, and hooks (not instructions) for anything that must be enforced.
So the root files hold commands, hard rules and pointers only, and code
structure stays in the handbook, read on demand.

## Sources (retrieved 18 and 19 November 2026)

- [Anthropic: how Claude remembers your project](https://code.claude.com/docs/en/memory):
  load order, `@AGENTS.md` import, size and writing guidance (19 November).
- [agents.md](https://agents.md): the tool-neutral format and nearest-file
  precedence (19 November).
- [HumanLayer: writing a good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md):
  universal instructions, progressive disclosure, no linter rules (19 November).
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

## GitHub CLI in Claude Code web sessions

There `gh issue list|view|edit|create` use GraphQL and fail with HTTP 403;
`scripts/ticket_digest.py` falls back to REST on that error. The repository must also be attached with
push access (otherwise REST returns 403 "access ... not enabled"). Use REST,
and keep field lists short:

```sh
R=repos/gmanldn/smoothcast
gh api "$R/issues?state=open&per_page=30" --jq '.[] | select(.pull_request|not) | "#\(.number) \(.title)"'
gh api "$R/issues/N" --jq '{number,title,state,assignees:[.assignees[].login],body}'
gh api -X POST "$R/issues/N/assignees" -f "assignees[]=$(gh api user --jq .login)"
gh api -X POST "$R/issues/N/comments" -f body='Claim: <agent>; scope: <files>'
```

`gh auth status` can report an invalid token while `gh api` works; trust
`gh api user`. Use `--paginate` for more than 100 issues.

## Complexity budget (#516)

`python3 scripts/ci/complexity_report.py` prints source size, the largest
modules and functions, startup imports and the bytes an agent reads first.
`docs/complexity-baseline.json` is a ratchet: `tests/test_complexity_budget.py`
fails only on unexplained growth (total +10%, a module +10%, a new module
over 1,200 lines). If growth is justified, refresh with `--write-baseline` and
say why in the commit message. Prefer extending or deleting code over adding a
module; see the strategy in #511.

## Advisory issue-body budget (#516)

`python3 scripts/ci/issue_body_budget.py --fetch` reports open, non-epic
GitHub issues whose **body alone** exceeds 6,000 UTF-8 bytes. The job runs in
the nightly workflow summary with read-only `issues: read` permission; the
report prints only issue numbers and byte counts, never issue-body text. It is
**advisory**, not a CI failure or substitute for detailed engineering briefs.

For deterministic offline review/tests, pass `--input export.json` containing
a JSON array shaped like GitHub's `/issues` response, or `--json` for compact
machine-readable output. The live fetch requires `GITHUB_TOKEN`; no issue is
changed, and a fetch failure is reported rather than inventing a clean result.
Move necessary detail into a short agent brief comment and link design docs;
do not delete important research merely to reduce byte counts.
