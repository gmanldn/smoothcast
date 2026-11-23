# SmoothCast — essentials for coding agents

Python 3.10+, GTK4/libadwaita, Chromecast and DLNA. Read only the **relevant**
topic in [agent handbook](docs/agents/README.md); run
`python3 scripts/agent_context.py route <task-or-path>` for a short route.
Do not load the [historical archive](docs/AGENT_REFERENCE.md) by default.

## Branch rule — read first

**`develop` is the only branch anyone commits to.** Never use the shared
checkout; push straight to `develop`, never with `--force`:

    git worktree add --detach ../smoothcast-N origin/develop
    # edit, test, commit, then:
    git fetch origin && git rebase origin/develop   # own unpushed commits only
    git push origin HEAD:develop

No feature branches or agent PRs. **Never commit, push, merge, open a
release PR against, or automatically promote `main`.** Only the owner may
explicitly merge `develop` into `main`. A push to `develop` is independent
of the state of `main`. See [workflow](docs/agents/workflow.md).

## Rules

- **GitHub Issues are authoritative:** use `python3 scripts/ticket_digest.py --next --label agent-ready`.
  Pick unclaimed P0/P1 issues and self-contained older fixes; claim by assignment
  and a short comment before editing, avoiding another agent's file scope.
  Push each coherent change directly to `develop` with `Refs #N`; report
  evidence honestly and close only when the issue's actual criteria are met.
  [Issues](docs/ISSUES.md).
- **Never lose work:** keep user changes, commits and stashes; no destructive cleanup.
- **Smallest complete fix:** inspect callers, reuse code, keep validation, privacy,
  device ownership and tests. [Ponytail](.kilo/skills/ponytail/SKILL.md).
- **Precise output:** results, evidence, blockers; never hide errors.
  [Caveman](.kilo/skills/caveman/SKILL.md).
- **Packaging authority:** `packaging/SmoothCast.spec` via `python3 scripts/build_release.py`; review [native packaging](docs/PACKAGING.md) before a release.
- **Versions:** only `src/version.py` is canonical. Bump PATCH on a
  completed ticket or explicit owner version request; refresh its current value
  before editing so parallel agents cannot overwrite one another.
  Git commit SHA identifies interim work.

## Parallel agents — fast, independent commits

**Do not hold a shared checkout, the index or a file-wide lock.** Use one
detached worktree per task. Claims are short-lived; take a bounded issue slice,
push it promptly, release the claim and take the next distinct issue. Fetch and
rebase **only your own unpushed commits** if another agent advanced `develop`.
Never force-push or rewrite published commits. Coordinate overlapping files.

**Tests are not a push prerequisite by owner request.** Do not start GTK or
a receiver to test a change. CI is **lazy, not absent**: security checks run
for risky changes; one nightly headless check batches many commits once the
owner manually merges that workflow into `main`; full Verify and native
packaging are on demand. None blocks routine `develop` commits or writes to
`main`. Never claim unrun tests passed; protect user data and active media.

[Architecture](docs/agents/architecture.md) ·
[Token efficiency](docs/agents/efficiency.md)
