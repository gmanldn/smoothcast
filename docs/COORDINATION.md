# Agent coordination — pick, claim, ship, close without collisions

## Coordination

One command, `python3 scripts/agent.py`, replaces the manual
digest → comment-claim → push → evidence loop. It reads state from GitHub and
git only; it never launches a GUI, never force-pushes and never closes a ticket
unless you pass `--close`.

```sh
python3 scripts/agent.py board                 # live claims, hot files, develop CI head
python3 scripts/agent.py next [--lane src/portal] [--later]   # best free ticket
python3 scripts/agent.py claim 207             # atomic claim; exit 3 = pick another
python3 scripts/agent.py ship                  # rebase + affected checks + push (--dry-run)
python3 scripts/agent.py done 207 --why "…" --checklist "…" [--close]
python3 scripts/agent.py heartbeat 207         # extend the lease on long work
python3 scripts/agent.py release 207 --note "…"
```

## Why collisions happened

Every agent posts as one GitHub user and claims with a free-text comment, so
the assignee field was never set (`ticket_digest` always showed `claimed=0`),
two agents picked the same top ticket within seconds, and nobody could see
which files another agent was already editing. Reds on `develop` came from
shared ratchets (complexity baseline, stale test expectations) that no agent
ran before pushing.

## The design

| Problem | Mechanism |
| --- | --- |
| Same ticket twice | `claim` posts a structured comment `<!-- sc-claim v1 agent=… ttl=… files=… -->`, then re-reads the feed. The **earliest** live claim wins; the loser deletes its own claim and exits 3. |
| Same files, different tickets | Each claim records the files it will edit (predicted from the ticket text, or `--files`). Another claim on any of them blocks `claim` and hides the ticket from `next`. Shared merge-friendly files (`pyproject.toml`, baselines, `verify.yml`, docs, tests) never block. |
| Dead agents hold tickets | Leases expire: 90 min default (30–180), refreshed by `heartbeat`. Legacy free-text `Claim:` comments count too (45 min) and end on "Claim released". |
| Choosing work | `next` scores each open ticket: tier (`now` 300, `next` 200, `later` 100) + priority (P0 150 … P3 0) + `agent-ready` + "already has shipped slices: finish it", minus recent churn (files changed on `develop` in the last 45 min), minus unmet prose dependencies, minus stale `in-flight` labels. Your own live claim always ranks first. `epic`, `icebox`, `needs-human` and `needs-split` are skipped. |
| Slow, noisy feedback | `ship` runs only what the change needs: compile + ruff on changed files, `mypy` only if a gated module changed, pytest for the changed test files, tests named after or importing each changed module, and three cheap ratchets (complexity, a11y, silent-except) whenever `src/` or a baseline changed. Typical push: seconds. Full suite stays MINOR/MAJOR only ([testing](agents/testing.md)). |
| Push races | `ship` fetches, rebases only your unpushed commits onto `origin/develop`, re-runs the checks, pushes `HEAD:develop`, and on rejection repeats up to 3 times. A rebase conflict aborts cleanly (exit 4); resolve by hand. |
| Evidence and closing | `done N` verifies HEAD is on `origin/develop`, derives the file list from commits mentioning `#N`, posts the compact comment from [ISSUES.md](ISSUES.md), releases the claim. Add `--close` only when every acceptance item passes. |

## Tiers

`now` = P0 safety, shipping blockers and tickets one slice from done;
`next` = remaining wave-1 quality work; `later` = wave-2 reach or gated on
another decision; `icebox` = parked. `now`/`next`/`later` are plain labels:
move a ticket by relabelling it. Gated families (Chrome Mesh behind #559,
mesh transfer behind #567/#568) stay `later`/`next` until the gate clears.

## Rules of the road

1. Start a session with `board`. A red `develop` head outranks new work.
2. `next` → `claim` → work in a detached worktree → `ship` → `done`.
   Exit code 3 from `claim` is normal: take the next suggestion, don't argue.
3. One agent per module family. `--lane src/portal` or `--lane mesh` lets
   several agents work in parallel lanes without fighting.
4. `src/cast_session.py`, `streamer.py`, `startup_cleanup.py` and `dlna.py`
   are plan-first: `claim` reminds you; comment a short plan before editing.
5. Hand back early: `release N --note "blocked by …"` is a success, not a failure.
6. Pushed a red head? Fix or revert before anything else; `ship` makes this rare.

Tests: `tests/test_agent_coordination.py` (pure core, no network).
