# SmoothCast — agent essentials

Python 3.10+, GTK4/libadwaita, Chromecast/DLNA. Read only the relevant
[handbook](docs/agents/README.md) topic. Use
`python3 scripts/agent_context.py route <task-or-path>`. The
[archive](docs/AGENT_REFERENCE.md) is historical, not default context.

## Branch and concurrent work

**Commit only to `develop`.** Never push, merge or open promotion PRs
against `main`; only the owner manually promotes it. Work in a **private
detached worktree**, never in the shared checkout:

```sh
git fetch origin develop
git worktree add --detach ../smoothcast-N origin/develop
# commit named files, mentioning Refs #N
git fetch origin develop && git rebase origin/develop
git push origin HEAD:develop
```

Rebase only your unpublished commits. Never force-push, reset user work or
delete others' worktrees/stashes. See [workflow](docs/agents/workflow.md).

## Ticket flow

GitHub Issues are authoritative: [issues](docs/ISSUES.md). Start with:

```sh
python3 scripts/agent.py board
python3 scripts/agent.py next
python3 scripts/agent.py claim N --files src/module.py
python3 scripts/agent.py ship
python3 scripts/agent.py done N --why "..." --checklist "..."
```

Read the chosen issue and recent comments. Exit 3 from `claim` means
another agent won: pick again. Release blocked claims promptly. Only close
when acceptance criteria actually pass. The fallback
`python3 scripts/ticket_digest.py --next --label agent-ready` is
read-only and **not claim-aware**; never assume its result is unclaimed.

## Quality and safety

- Small, complete, well-scoped patches; explain real evidence and blockers.
  Tests are optional on `develop`, but never assert unrun checks passed.
- **Never launch the real GUI** or control real receivers during tests.
  Read [testing](docs/agents/testing.md); use
  `scripts/test_gui_isolated.py`. Full opt-in tests:
  `python3 -m pytest -q tests`.
- Respect playback ownership, privacy, compatibility and error paths.
  See [architecture](docs/agents/architecture.md).
- Keep context bounded: [efficiency](docs/agents/efficiency.md),
  [Ponytail](.kilo/skills/ponytail/SKILL.md),
  [Caveman](.kilo/skills/caveman/SKILL.md).
- `src/version.py` is canonical; bump PATCH on a completed ticket or
  explicit request after refreshing `develop`. Interim work is identified
  by commit SHA. Packaging authority: `packaging/SmoothCast.spec`.
