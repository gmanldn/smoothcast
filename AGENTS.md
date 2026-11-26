# SmoothCast — agent essentials

Python 3.10+, GTK4/libadwaita, Chromecast/DLNA. Read only the relevant
[handbook](docs/agents/README.md) topic. Use
`python3 scripts/agent_context.py route <task-or-path>`.
The [archive](docs/AGENT_REFERENCE.md) is historical, not policy.

## Hosted ChatGPT containers: connector-first (P0)

**Treat hosted ChatGPT execution containers as offline.** They have no usable
native internet access for GitHub or dependency downloads. Use the GitHub
connector for repository reads, issue claims, commits and guarded pushes to
`develop` from the outset. Do not waste time on repeated `git pull`, `gh`,
`curl`, DNS probes, package downloads or network workarounds in these containers.
Use available local tools for offline checks only; report unavailable checks as
UNVERIFIED. This is an agent environment restriction, not a SmoothCast runtime
networking bug. Follow the [connector shipment procedure](docs/agents/sandbox-network.md).
Native Git remains the preferred workflow on machines with working access.

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

- Small, complete, well-scoped patches; explain real evidence.
  Tests are deferred on `develop`: ship work, test lazily; never claim unrun
  checks passed.
- **Never launch the real GUI** or control real receivers during tests. See
  [testing](docs/agents/testing.md); use `scripts/test_gui_isolated.py`; full
  suite: `python3 -m pytest -q tests`.
- Respect playback ownership, privacy, compatibility and errors; see
  [architecture](docs/agents/architecture.md).
- **Token discipline:** [Ponytail](.kilo/skills/ponytail/SKILL.md) for the
  smallest complete diff, [Caveman](.kilo/skills/caveman/SKILL.md) for terse
  evidence; see [efficiency](docs/agents/efficiency.md). Correctness wins.
- Owner policy (26 Nov 2026): **make new versions in `develop`**. Merge work and
  bump SemVer (`src/version.py`, `smoothcast --version`) there as owner-directed
  release commits; `main` stays owner-promoted only. Old `--assign-patch` is
  ignored; Git commit SHA identifies every build (`--build-id`). Mandatory
  version-history checks run on every ship, even with `--skip-checks`. Never
  bypass via raw pushes. No automatic merging, tagging or publishing to `main`.
  Packaging authority: `packaging/SmoothCast.spec`.
