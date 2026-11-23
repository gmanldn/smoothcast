# Contributing to SmoothCast

**Develop-only working policy.** `develop` is the sole development branch.
`main` is untouched by agents, CI and automatic workflows. Only the project
owner may manually integrate `develop` into `main`; version bumps do not
trigger automatic promotion or publication.

GitHub Issues are the authoritative backlog:
[docs/ISSUES.md](docs/ISSUES.md). The short canonical operating rules are
[AGENTS.md](AGENTS.md) and [docs/agents/workflow.md](docs/agents/workflow.md).

## Maintainers and agents

1. Use `python3 scripts/agent.py start` to claim the highest-ranked
   available ticket, or `start N` for a specific one. It refreshes develop,
   creates a private detached worktree and saves a short issue/handover brief.
2. In the printed worktree, implement a coherent slice and call
   `python3 scripts/agent.py ship --message "fix: specific result"`.
   Tracked edits are committed privately; name new files with `--files`.
   The command verifies the current lease, rebases only unpublished work,
   checks version history, fast-forward pushes and posts a SHA handover.
3. Call `python3 scripts/agent.py finish --done "..." --next "..."`
   to record what landed, what remains and release the lease. Add explicit
   real `--verification`, `--checklist`, `--next none` and `--close`
   only when all acceptance criteria are met.

Never force-push or reset another agent's work. Use `--skip-checks` only
when deliberately leaving a slice unverified; integrity checks are mandatory.
Relevant tests run selectively; no GUI or real receivers during tests.

External contributors without push access may propose PRs targeting
`develop`. Maintainers and agents do not open topic branches or PRs.

## Version and main

`src/version.py` is release SemVer, not a per-ticket counter. Routine agent
shipments retain the version and use the Git commit SHA as the unique build
identity (`smoothcast --build-id`). `agent.py ship --assign-patch` is a
strictly explicit, owner-authorised operation, never the default. `main`
integration, release tags and publication are entirely manual owner actions.

Security issues: [SECURITY.md](SECURITY.md).
