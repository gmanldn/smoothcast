# Agent coordination — pick, claim, ship, close without collisions

## Coordination

One command, `python3 scripts/agent.py`, replaces the manual
digest → comment-claim → push → evidence loop. It reads state from GitHub and
git only; it never launches a GUI, never force-pushes and never closes a ticket
unless you pass `--close`. Its `done` report defaults to **unverified**;
pass explicit evidence when checks have actually been run.

```sh
python3 scripts/agent.py board                 # claims, hot files, optional CI summary
python3 scripts/agent.py next [--lane src/portal] [--later]   # best free ticket
python3 scripts/agent.py claim 207             # atomic claim; exit 3 = pick another
python3 scripts/agent.py ship --skip-checks    # rebase + push quickly, UNVERIFIED
python3 scripts/agent.py ship                  # optional affected checks + push
python3 scripts/agent.py progress 207 --done "landed …" --next "remaining …" --commit SHA --verification "actual result" --release
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
| Fast direct commits | `ship --skip-checks` rebases and pushes directly without running tests. Plain `ship` retains optional focused checks. An unverified push must be reported as such, never as successful testing. |
| Push races | `ship` fetches, rebases only your unpushed commits onto `origin/develop`, re-runs the checks, pushes `HEAD:develop`, and on rejection repeats up to 3 times. A rebase conflict aborts cleanly (exit 4); resolve by hand. |
| Durable handover | `progress N --done … --next … --commit SHA --verification … [--files …] [--release]` posts `Progress:`, `Handover:`, `Commit:`, `Verification:` and `Files:` in the issue. `next` previews the latest progress and remaining work on shortlisted tickets. Evidence persists long after the lease expires. |\n| Evidence and closing | `done N` verifies HEAD is on `origin/develop`, derives the file list from commits mentioning `#N`, posts the compact comment from [ISSUES.md](ISSUES.md), releases the claim. Add `--close` only when every acceptance item passes. |

## Tiers

`now` = P0 safety, shipping blockers and tickets one slice from done;
`next` = remaining wave-1 quality work; `later` = wave-2 reach or gated on
another decision; `icebox` = parked. `now`/`next`/`later` are plain labels:
move a ticket by relabelling it. Gated families (Chrome Mesh behind #559,
mesh transfer behind #567/#568) stay `later`/`next` until the gate clears.

## Rules of the road

1. Start with `board` for current claims and hot files. CI is manual and must not be mistaken for a required develop push gate.
2. `next` → inspect earlier `Progress:`/`Implementation:`/`Handover:` comments
   **and shipped source** → `claim` → detached worktree → `ship` →
   `progress --release` (or `done` when all criteria are evidenced).
   Exit code 3 from `claim` is normal: take the next suggestion, don't argue.
3. One agent per module family. `--lane src/portal` or `--lane mesh` lets
   several agents work in parallel lanes without fighting.
4. `src/cast_session.py`, `streamer.py`, `startup_cleanup.py` and `dlna.py`
   are plan-first: `claim` reminds you; comment a short plan before editing.
5. Hand back early: `progress N --done "what landed or not pushed" --next "specific remaining work" --verification "actual checks or not run" --release` is a success, not a failure. A claim is a **90-minute default lease** (30–180 configurable), not ownership. `heartbeat` only when work actively continues. An expired lease does not erase prior comments or commits; review both before taking over. An assignee or stale `in-flight` label is not a lock.
6. If a regression is discovered, prioritise a corrective commit or safe revert. Untested changes must not be described as verified.

Tests: `tests/test_agent_coordination.py` (pure core, no network).


## Claim and completion safety

Structured claim events replay in immutable GitHub comment-ID order. A heartbeat
updates only an **active** lease; it cannot reopen an expired or released claim.
Before assigning the shared GitHub user or marking `in-flight`, `claim` confirms
its own comment is visible, retrying the issue's comment feed when the global
feed lags. If confirmation fails, it withdraws and returns exit 3 rather than
pretending it owns the ticket.

`done --close` uses GitHub REST and checks the returned state. If GitHub does
not confirm closure, it reports an error rather than claiming success. Agent
coordination remains usable on Python 3.10 without a TOML dependency.
