# SmoothCast — agent essentials

Python 3.10+, GTK4/libadwaita, Chromecast/DLNA. Read only the relevant
[handbook](docs/agents/README.md) topic. Use
`python3 scripts/agent_context.py route <task-or-path>`.
The [archive](docs/AGENT_REFERENCE.md) is historical, not policy.

## Fast agent lifecycle (P0)

**Only develop receives agent code. Main is manually promoted by the owner.**
Never push/merge/promote/tag main. Never reset another agent's work or force-push.
Use a private detached worktree; one ticket per worktree.

```sh
python3 scripts/agent.py start              # choose the next available ticket
# cd into the printed worktree; read its private task brief
python3 scripts/agent.py ship --message "fix: concrete result"
python3 scripts/agent.py finish --done "landed implementation" --next "remaining tests" --verification "not run (unverified)"
# To close: --next none --verification "actual test results" --checklist "all criteria" --close
```

`start` refreshes `develop`, claims a 90m lease and opens a private worktree
with a compact brief; commits persist. `ship` commits tracked
edits (`--files` for new files), reconciles leases, checks version integrity and
pushes non-force. Preserve conflicts; after exit 5/7 rerun `ship` in the same
worktree, never recommit or overwrite another checkout. New paths expand the
lease; missing optional checks are UNVERIFIED. `finish` records
evidence and releases the lease. See
[coordination](docs/COORDINATION.md) and [workflow](docs/agents/workflow.md).
GitHub Issues are authoritative ([issue rules](docs/ISSUES.md)); the read-only
`scripts/ticket_digest.py --next --label agent-ready` is not claim-aware.

## Product rule: effortless UX (P0)

- User experience is paramount. SmoothCast handles discovery, routing,
  workers, recovery and cleanup; users choose media and targets.
- Keep the happy path fast and obvious; disclose diagnostics progressively.
  Never fake readiness or success, hide a real failure, or weaken consent/security.
- Keep GTK/browser interaction responsive: bounded off-thread I/O, coalesced
  updates, no duplicate pollers or needless redraws. Preserve input and playback.
  See [UX and orchestration](docs/agents/preferences.md#ux-and-orchestration).

## Quality and safety

- Small, complete, well-scoped patches; explain real evidence and blockers.
  Tests are optional on `develop`, but never assert unrun checks passed.
- **Never launch the real GUI** or control real receivers during tests.
  Read [testing](docs/agents/testing.md); use
  `scripts/test_gui_isolated.py`; full suite:
  `python3 -m pytest -q tests`.
- Respect playback ownership, privacy, compatibility and errors; see
  [architecture](docs/agents/architecture.md).
- **Token discipline:** [Ponytail](.kilo/skills/ponytail/SKILL.md) for the
  smallest complete diff, [Caveman](.kilo/skills/caveman/SKILL.md) for terse
  evidence; see [efficiency](docs/agents/efficiency.md). Correctness wins.
- Owner policy (25 Nov 2026): **no per-ticket version bumps**. Ship and close
  verified tickets immediately using Git commit SHA; only explicit owner-directed
  release changes edit SemVer (`src/version.py`, `smoothcast --version`).
  Old `--assign-patch` is ignored; Git commit SHA identifies every build (`--build-id`).
  Mandatory version-history checks run on every ship, even with `--skip-checks`.
  Never bypass via raw pushes. No automatic merging, tagging or publishing to `main`.
  Packaging authority: `packaging/SmoothCast.spec`.
