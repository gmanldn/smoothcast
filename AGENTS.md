# SmoothCast — agent operating contract

SmoothCast is a Python 3.10+ GTK4/libadwaita video player and Chromecast/DLNA
companion. The full pre-compaction agent instructions and implementation notes
are **preserved** at [docs/AGENT_REFERENCE.md](docs/AGENT_REFERENCE.md).
Read that reference selectively when the task requires a specific subsystem.
Current rules in this file take precedence over outdated notes there.

## Start here

- Locate the affected functions and callers before editing. Read relevant
  sections, **not** all source files or complete historical logs by default.
- Use the existing implementation, Python standard library and installed
  dependencies. Avoid new abstractions and packages unless required.
- Finish the complete change: callers, error handling, compatibility and
  targeted tests. Never trade away security, validation, accessibility or
  reliable playback to make a patch smaller.
- Preserve local commits, worktrees, stashes and uncommitted user changes.
  Do not force-reset or overwrite work. Commit and push cohesive, tested work.
- Canonical release version: `src/version.py`; never bump per commit.
  Check the running release with `./smoothcast --version` (no GUI launch).
  Use the Git commit SHA to identify intermediate changes. Update the
  relevant GitHub Issue honestly; do not mark hardware-dependent behaviour
  verified without real-device testing.

## Issue ownership — required

- Read [the GitHub Issues workflow](docs/ISSUES.md) and the specific issue
  before editing. Priorities and stable legacy IDs live in issue titles:
  `[P0][SC-058]`, for example; `SC-058` is **not** GitHub issue #58.
- Claim work in the issue, use isolated worktrees and link PRs. Only close an
  issue once its **full** tests and real-device requirements pass. Existing
  code without hardware validation remains open.
- Create new feature requests in GitHub Issues; never recreate the removed
  root backlog. Preserve original paid research and migrated source links.

## Token-efficient agent behaviour

**Caveman:** answer first, concise British English, no ceremonial opener or
repeated summary. Keep negation, errors, commands, paths, version numbers and
uncertainty exact; do **not** rewrite user prompts or shorten code payloads.
See [Caveman skill](.kilo/skills/caveman/SKILL.md).

**Ponytail:** write the smallest *complete* diff: reuse helpers, avoid speculative
features, layers and dependencies, and test nontrivial logic. Optimise
maintainability and correctness, not arbitrary line counts.
See [Ponytail skill](.kilo/skills/ponytail/SKILL.md).

- Prefer targeted symbol/search queries, `git diff --stat` and
  `pytest -q tests/test_relevant.py` before broad scans.
- Summarise successful test output; retain full output on disk for failures.
  Never hide a failure, exception, stack trace or evidence needed to debug.
- Do not assume a token-savings percentage or install a proxy on the user's
  machine without explicit approval. See
  [token-efficiency guide](docs/AGENT_TOKEN_EFFICIENCY.md).

## Non-negotiable test safety

**Do not launch/focus the real app while testing.** Never invoke
`./smoothcast`, `gtk-launch`, `python3 src/cast_control.py`, or plain
`--self-test` during routine tests. Never use the user's active display,
Wayland session or desktop DBus.

- Headless suite: `python3 -m pytest -q tests`
- Syntax: `python3 -m compileall -q src scripts setup tests`
- Optional **explicit** GTK smoke test:
  `python3 scripts/test_gui_isolated.py` on disposable Xvfb, not in pytest.
  Its runtime, HOME and session credentials must stay isolated.
- CI runs the portable headless suite; real-TV results require separate
  opt-in device testing. Normal tests must not modify user media or desktop
  integration.

## Navigation

- UI/preview: `src/cast_control.py`, `src/responsive_layout.py`,
  `src/local_playback.py`; media/transcoding: `src/streamer.py`,
  `src/preflight.py`, `src/subtitle_encoding.py`
- Cast: `src/castctl.py`; DLNA: `src/dlna.py`; diagnostics:
  `src/diagnostics.py`; desktop/setup: `setup/`, `scripts/install_desktop.py`
- Tests: `tests/`; CI: `.github/workflows/verify.yml`;
  **canonical issues/backlog:** [GitHub Issues](https://github.com/gmanldn/smoothcast/issues)
  and `docs/ISSUES.md` (the old root Markdown backlog has been retired)
- Extensive architectural caveats, history, performance notes and device
  safety details: [full agent reference](docs/AGENT_REFERENCE.md).
