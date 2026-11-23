# Exact-head CI verdict for agents (#546)

Use this bounded, read-only command **after pushing to develop**:

    python3 scripts/ci/head_verdict.py
    python3 scripts/ci/head_verdict.py --json
    python3 scripts/ci/head_verdict.py --software-only --json
    python3 scripts/ci/head_verdict.py --head "$(git rev-parse origin/develop)"

Requires an authenticated GitHub CLI (\`gh auth login\`). No Python packages,
GUI, Git writes, issue edits, receivers, or credentials are stored. It reads
the live develop ref twice and inspects only exact-SHA push workflows and the
matching Verify SmoothCast jobs. Intermediate runs cancelled by CI coalescing
cannot be treated as green. If the branch disappears during automated release
PR merging, it fails closed and reports the missing ref.

**Default exit codes:** 0 only when the exact current SHA has a completed,
green Verify SmoothCast workflow, required patch-lane jobs passed, and all
observed push workflows succeeded. 1 for definitive failure, including a
blocked promotion. 2 for pending/stale/unknown or unavailable GitHub data.

**`--software-only`** is the safe ticket-completion gate, NOT a publishing
check: exit 0 only when the current develop SHA has a completed Verify run,
every required and executed non-promotion job and observed external workflow
passed, and any overall Verify failure is attributable solely to its final
promotion job. Failures, missing jobs, stale heads, pending or cancelled runs
remain nonzero. JSON reports the independent `software_qualified` boolean;
`release: "blocked"` remains visible if MainProtector prevented publication.
Never claim that `--software-only` released anything to `main`.

No single passed job is proof that software acceptance or publication passed.

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
