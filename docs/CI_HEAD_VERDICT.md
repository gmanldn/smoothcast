# Exact-head CI verdict for agents (#546)

Use this bounded, read-only command **after pushing to develop**:

    python3 scripts/ci/head_verdict.py
    python3 scripts/ci/head_verdict.py --json
    python3 scripts/ci/head_verdict.py --head "$(git rev-parse origin/develop)"

Requires an authenticated GitHub CLI (\`gh auth login\`). No Python packages,
GUI, Git writes, issue edits, receivers, or credentials are stored. It reads
the live develop ref twice and inspects only exact-SHA push workflows and the
matching Verify SmoothCast jobs. Intermediate runs cancelled by CI coalescing
cannot be treated as green. If the branch disappears during automated release
PR merging, it fails closed and reports the missing ref.

**Exit codes:** 0 only when the exact current SHA has a completed, green
Verify SmoothCast workflow, required patch-lane jobs passed, and all other
triggered push workflows observed for the SHA succeeded. 1 for definitive
failure, including blocked release promotion. 2 for pending/stale/unknown or
unavailable GitHub data. No single passed job is proof the workflow passed.

\`software\` indicates required tests/linters and triggered security/package
workflow status. \`release\` separately distinguishes \`passed\`,
\`not_required\`, \`pending\` and \`blocked\`; a MainProtector rejection or a
deleted develop ref never becomes a success. \`checks\` lists other observed
push workflows. Because GitHub may queue or omit a workflow not yet triggered,
this is a conservative *point-in-time* verdict, not future-release or
physical-receiver certification. GitHub Issue acceptance criteria still have
to be reviewed before closing the ticket.

Use \`--json\` when reporting in a coding-agent workflow instead of pasting
multiple full Actions run objects into the prompt. This reduces redundant
manual API reads; it does **not** prove a provider-billed token saving without
before/after usage data.
