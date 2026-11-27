# SmoothCast — agent essentials

Python 3.10+, GTK4/libadwaita, Cast/DLNA. Route tasks via
`python3 scripts/agent_context.py route <task-or-path>` and the
[handbook](docs/agents/README.md). [Archive](docs/AGENT_REFERENCE.md) is history,
not policy. [Issues](docs/ISSUES.md) are authoritative.

## Transport and lifecycle (P0)

Hosted ChatGPT containers: assume offline for native Git/gh/curl/downloads.
Use the GitHub connector first, with the [guarded transport](docs/agents/sandbox-network.md).
Native Git remains preferred on connected machines.
Only `develop` receives agent changes; `main` is owner-controlled. Never
force-push, reset another agent's work, auto-promote, tag or publish main.

```sh
python3 scripts/agent.py start
# cd into the printed worktree; read the task brief
python3 scripts/agent.py ship --message "fix: concrete result"
python3 scripts/agent.py finish --done "landed" --next "remaining checks" --verification "not run (unverified)"
```

Work only in private detached worktrees, not the owner checkout. Claim only
production files edited, prefer 30-minute slices and release promptly with
durable SHA, checks and next action. Use `agent.py scope --files src/one.py`
to relinquish unused scope. Never bypass overlapping live leases. Stage named
files; ship non-force. On exit 5/7 rerun ship in the same worktree to reconcile.
See [workflow](docs/agents/workflow.md) and [coordination](docs/COORDINATION.md).
Close only with demonstrated acceptance. `ticket_digest.py --next` is not
claim-aware.

## Version and journal (P0)

`src/version.py` is canonical (`--version`); Git commit SHA identifies every
build. Strongly prefer automatic +1 PATCH per nonempty develop shipment, not
per ticket, without owner approval. MINOR/MAJOR remain owner-directed. If PATCH
allocation alone fails, ship at unchanged valid version. Never bypass history
integrity, even with `--skip-checks`. No release qualification blocks a
coherent develop push. Every shipment generates the root
[CHANGELOG.md](CHANGELOG.md) from fresh history; never hand-edit or lease it.
See [journal rules](docs/CHANGELOG.md). Packaging: `packaging/SmoothCast.spec`.

## Product and quality (P0)

UX first: users choose media and targets; SmoothCast handles discovery, routing,
workers, recovery and cleanup. Keep GTK/browser controls responsive: bounded
off-thread I/O, coalesced updates, no redundant polls/redraws. Preserve input,
playback, ownership, privacy and consent. Never fake readiness, hide failure or
weaken security. [UX](docs/agents/preferences.md#ux-and-orchestration) and
[architecture](docs/agents/architecture.md).

Ship small complete slices promptly. Test lazily; hardware/device qualification
is desirable but never blocks develop. Record skipped checks UNVERIFIED;
ticket acceptance and release qualification are distinct. Lease, non-force
and version-integrity guards still apply. **Never launch the real GUI** or
control real receivers in tests. Use `scripts/test_gui_isolated.py`; full suite
`python3 -m pytest -q tests`. See [testing](docs/agents/testing.md).
Follow [Ponytail](.kilo/skills/ponytail/SKILL.md) and
[Caveman](.kilo/skills/caveman/SKILL.md); [efficiency](docs/agents/efficiency.md).
Smallest correct diff, terse evidence; correctness wins.
