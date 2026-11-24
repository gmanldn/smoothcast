# SmoothCast — agent essentials

Python 3.10+, GTK4/libadwaita, Chromecast/DLNA. Read only the relevant
[handbook](docs/agents/README.md) topic. Use
`python3 scripts/agent_context.py route <task-or-path>`. The
[archive](docs/AGENT_REFERENCE.md) is historical, not default context.

## Fast agent lifecycle (P0)

**Only develop receives agent code. Main is manually promoted by the owner.**
Never push/merge/promote/tag main. Never reset another agent's work or force-push.
Use a private detached worktree; one ticket per worktree.

```sh
python3 scripts/agent.py start              # choose the next available ticket
python3 scripts/agent.py start 584          # or choose an explicit issue
# cd into the printed worktree; read its private task brief
python3 scripts/agent.py ship --message "fix: concrete result"
python3 scripts/agent.py finish --done "landed implementation" --next "remaining tests" --verification "not run (unverified)"
# To close: --next none --verification "actual test results" --checklist "all criteria" --close
```

`start` atomically claims a short lease, refreshes develop, creates an isolated
worktree and leaves issue body + latest handover in that worktree's Git admin
directory. Claims expire (90m default), but progress comments and pushed SHAs
persist; read both before taking over. `ship` auto-commits tracked edits only
inside a coordinator-created worktree; use `--files` for new files. Without
`--message`, commit named files yourself first. It fetches, rebases only
unpublished work, checks every version transition even with `--skip-checks`,
pushes non-force and posts a durable handover. On conflicts, preserve the
worktree and reconcile intentionally. Never claim unrun checks passed.
`finish` records actual outcomes and releases the lease. A `ship` exit
code **7** means the code **already reached develop** but GitHub handover is
pending: rerun `agent.py ship` from the SAME worktree to replay the saved
SHA receipt; **do not recommit**. Newly touched production files trigger
race-arbitrated lease expansion before push. Missing optional checks are
reported as unverified, never as passing. Follow
[coordination](docs/COORDINATION.md) and [workflow](docs/agents/workflow.md).
GitHub Issues are authoritative ([issue rules](docs/ISSUES.md)); the read-only
`scripts/ticket_digest.py --next --label agent-ready` is not claim-aware.

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
- `src/version.py` is release SemVer; agent shipments do **not** automatically
  bump it. Each develop revision has its Git commit SHA (`smoothcast
  --build-id`). `smoothcast --version` retains stable SemVer.
  `agent.py ship --assign-patch` is an **explicit opt-in**, requiring owner
  authorisation, never the normal path. The version-history check runs on
  every `ship` even with `--skip-checks`. Never bypass it via raw pushes.
  No automatic merging, tagging or publishing to `main`.
  Packaging authority: `packaging/SmoothCast.spec`.
