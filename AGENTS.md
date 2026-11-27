# SmoothCast — agent essentials

Python 3.10+, GTK4/libadwaita, Chromecast/DLNA. Read only the relevant
[handbook](docs/agents/README.md) topic. Use
`python3 scripts/agent_context.py route <task-or-path>`.
The [archive](docs/AGENT_REFERENCE.md) is historical, not policy.

## Hosted ChatGPT containers: connector-first (P0)

**Treat hosted ChatGPT execution containers as offline** for native Git, gh,
curl and dependency downloads — an environment limit, not a runtime networking
bug. Use the GitHub connector from the outset for reads, claims,
commits and guarded `develop` pushes per the
[connector shipment rules](docs/agents/sandbox-network.md); report unrun checks
as UNVERIFIED. Native Git stays preferred where access works.

## Fast agent lifecycle (P0)

**Only develop receives agent code. Main is manually promoted by the owner.**
Never push/merge/promote/tag main. Never reset another agent's work or force-push.
Edit only in a private detached worktree, never the owner checkout.

```sh
python3 scripts/agent.py start              # choose the next available ticket
# cd into the printed worktree; read its task brief
python3 scripts/agent.py ship --message "fix: concrete result"
python3 scripts/agent.py finish --done "landed implementation" --next "remaining tests" --verification "not run (unverified)"
```

`start` refreshes `develop`, claims a 90m lease and opens a private worktree;
`ship` commits tracked edits (`--files` for new files), reconciles leases,
checks version integrity and pushes non-force (after exit 5/7 rerun `ship` in
the same worktree). `finish` records evidence and releases the lease. See
[coordination](docs/COORDINATION.md) and [workflow](docs/agents/workflow.md).
GitHub Issues ([docs/ISSUES.md](docs/ISSUES.md)) are authoritative; the read-only
`scripts/ticket_digest.py --next --label agent-ready` is not claim-aware.

## Product rule: effortless UX (P0)

- User experience is paramount. SmoothCast handles discovery, routing,
  workers, recovery and cleanup; users choose media and targets.
- Keep the happy path fast; disclose diagnostics progressively. Never fake
  readiness or success, hide a real failure, or weaken consent/security.
- Keep GTK/browser interaction responsive: bounded off-thread I/O, coalesced
  updates, no duplicate pollers or needless redraws. Preserve input and playback.
  See [UX and orchestration](docs/agents/preferences.md#ux-and-orchestration).

## Quality and safety

- Small, complete, well-scoped patches; explain real evidence. Tests are
  deferred on `develop`: ship work, test lazily; never claim unrun checks passed.
- Owner policy (27 Nov 2026): physical hardware/device testing is desirable,
  **never a prerequisite for a `develop` push**. Ship coherent work promptly;
  record unrun hardware checks as UNVERIFIED. Keep release qualification and
  ticket acceptance evidence separate from shipment. Lease, version-integrity
  and non-force publication safeguards still apply.
- **Never launch the real GUI** or control real receivers during tests. See
  [testing](docs/agents/testing.md); use `scripts/test_gui_isolated.py`; full
  suite: `python3 -m pytest -q tests`.
- Respect playback ownership, privacy, compatibility and errors; see
  [architecture](docs/agents/architecture.md).
- **Token discipline:** [Ponytail](.kilo/skills/ponytail/SKILL.md) for the
  smallest complete diff, [Caveman](.kilo/skills/caveman/SKILL.md) for terse
  evidence; see [efficiency](docs/agents/efficiency.md). Correctness wins.
- Owner policy (27 Nov 2026): **agents may freely bump PATCH in `develop`**, never on
  `main`; no per-bump owner approval is required. Increment the latest canonical
  `src/version.py` PATCH by one using the guarded release lane; MINOR and MAJOR
  remain owner-directed. This standing authorisation supersedes any older
  owner-only PATCH restriction in child documents. Git commit SHA identifies every build; version-history checks
  run on every ship, even with `--skip-checks`. No auto main merge/tag/publish.
  Packaging: `packaging/SmoothCast.spec`.
