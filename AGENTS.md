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

No feature branches, no agent PRs. **Never commit or push to `main`:** it is
release-only and updated by an automatic develop→main PR when
`src/version.py` is bumped (`scripts/ci/bump_version.py`). A red `develop` is
everyone's top priority. See [workflow](docs/agents/workflow.md).

## Rules

- **Issues are authoritative:** `python3 scripts/ticket_digest.py --next`, claim
  before work, `Refs #N` in commits, close only when every acceptance criterion
  (incl. hardware) is verified. [Issues](docs/ISSUES.md).
- **Never lose work:** keep user changes, commits and stashes; no destructive cleanup.
- **Smallest complete fix:** inspect callers, reuse code, keep validation, privacy,
  device ownership and tests. [Ponytail](.kilo/skills/ponytail/SKILL.md).
- **Precise output:** results, evidence, blockers; never hide errors.
  [Caveman](.kilo/skills/caveman/SKILL.md).
- **Release authority:** `src/version.py`; the commit SHA names a dev revision.

## Testing — no desktop focus

**Never launch the real GUI, activate the user's window or control their TV
during routine tests.** No `gtk-launch`, `./smoothcast` or bare `--self-test`.
Use `python3 -m pytest -q tests` and
`python3 -m compileall -q src scripts setup tests`. Optional GUI smoke:
`python3 scripts/test_gui_isolated.py` (private Xvfb only).
[Test safety](docs/agents/testing.md).

[Architecture](docs/agents/architecture.md) ·
[Token efficiency](docs/agents/efficiency.md)
