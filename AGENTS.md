# SmoothCast — essentials for coding agents

Python 3.10+, GTK4/libadwaita, FFmpeg, Chromecast (`catt`) and DLNA. Read only
the relevant topic in the [agent handbook](docs/agents/README.md); get a route
with `python3 scripts/agent_context.py route <task-or-path>`. Never load the
[historical archive](docs/AGENT_REFERENCE.md) by default.

## Commands

- Test: `python3 -m pytest -q tests` (one file: `... tests/test_x.py`)
- Syntax: `python3 -m compileall -q src scripts setup tests`
- Version: `./smoothcast --version` (GUI-free)
- Next issue: `python3 scripts/ticket_digest.py --next`

## Rules

- **GitHub Issues are authoritative.** Read and claim an issue before work, use
  a branch or worktree, close only when every acceptance criterion (including
  hardware checks) is verified. Legacy `SC-nnn` IDs are not issue numbers. See
  [workflow](docs/agents/workflow.md) and [issues](docs/ISSUES.md).
- **Never lose work:** keep user changes, commits and stashes; no force-reset.
- **Smallest complete fix:** read callers, reuse code, keep validation, device
  ownership and regression tests. [Ponytail](.kilo/skills/ponytail/SKILL.md)
- **Exact, concise output:** results, evidence, blockers; never hide errors.
  [Caveman](.kilo/skills/caveman/SKILL.md)
- **Never claim device verification from CI;** state what was not tested.
- **Release authority:** `src/version.py`, not each commit; a commit is
  identified by its Git commit SHA.

## Testing — no desktop focus

**Never launch the real GUI, activate the user's window or control their TV
during routine tests.** No `gtk-launch`, `./smoothcast` (except `--version`)
or bare `--self-test`. GUI smoke only via `python3 scripts/test_gui_isolated.py`
(private Xvfb). See [test safety](docs/agents/testing.md).

## Find what you need

[Workflow](docs/agents/workflow.md) · [Testing](docs/agents/testing.md) ·
[Architecture](docs/agents/architecture.md) ·
[Efficiency](docs/agents/efficiency.md) · [Archive](docs/AGENT_REFERENCE.md)
