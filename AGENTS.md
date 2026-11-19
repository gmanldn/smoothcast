# SmoothCast — essentials for coding agents

Python 3.10+, GTK4/libadwaita, Chromecast and DLNA. Read only the **relevant**
topic in [agent handbook](docs/agents/README.md); run
`python3 scripts/agent_context.py route <task-or-path>` for a short route.
Do not load the entire handbook or
[historical archive](docs/AGENT_REFERENCE.md) by default.

## Rules

- **GitHub Issues are authoritative:** start with
  `python3 scripts/ticket_digest.py --next` for the next unclaimed issue, then
  read and claim that issue before work; work on an isolated branch/worktree and
  open PRs against **`develop`** (`main` is protected, release-only), closing
  only when all acceptance criteria (including hardware checks if required) are
  verified. See [workflow](docs/agents/workflow.md) and
  [issues](docs/ISSUES.md).
- **Never lose work:** preserve user changes, local commits and stashes; no
  force-reset or destructive cleanup. Commit and push tested, cohesive fixes.
- **Smallest complete fix:** inspect callers; reuse existing code; retain
  validation, privacy, device ownership, compatibility and regression tests.
  [Ponytail](.kilo/skills/ponytail/SKILL.md).
- **Precise, concise output:** results, evidence and blockers; never hide
  errors or compress commands/code inaccurately.
  [Caveman](.kilo/skills/caveman/SKILL.md).
- **Packaging authority:** `packaging/SmoothCast.spec` via `python scripts/build_release.py`; read [packaging guide](docs/PACKAGING.md) before release. Source installers are development paths.\n- **Release authority:** `src/version.py`, not every Git commit. The Git commit SHA
  identifies a development revision; `./smoothcast --version` is GUI-free.

## Testing — no desktop focus

**Never launch the real GUI, activate the user's window or control their TV
during routine tests.** Do not run `gtk-launch`, `./smoothcast` or bare
`--self-test` to test. Use `python3 -m pytest -q tests` and
`python3 -m compileall -q src scripts setup tests`. Optional explicit GUI
smoke: `python3 scripts/test_gui_isolated.py` (private Xvfb only).
See [test safety](docs/agents/testing.md).

## Find what you need

[Workflow](docs/agents/workflow.md) ·
[Testing](docs/agents/testing.md) ·
[Architecture and code map](docs/agents/architecture.md) ·
[Token efficiency](docs/agents/efficiency.md) ·
[Full historical notes](docs/AGENT_REFERENCE.md).
