# Contributing to SmoothCast

**Develop-only working policy.** `develop` is the sole development branch.
`main` is untouched by agents, CI and automatic workflows. Only the project
owner may manually integrate `develop` into `main`; version bumps do not
trigger automatic promotion or publication.

GitHub Issues are the authoritative backlog:
[docs/ISSUES.md](docs/ISSUES.md). The short canonical operating rules are
[AGENTS.md](AGENTS.md) and [docs/agents/workflow.md](docs/agents/workflow.md).

## Maintainers and agents

1. Start with `python3 scripts/agent.py board` and `agent.py next`;
   choose an available issue using live claims and hot file scopes.
2. Claim briefly, use your own **detached worktree** of `origin/develop`, and
   commit one small coherent slice with `Refs #N`.
3. Fetch and rebase **only your own unpublished work**, then fast-forward push
   to `origin/develop` directly. Never force-push or overwrite another agent's
   worktree, uncommitted changes or version bump.
4. Release the claim, document the exact SHA and test status, and take the next
   available task. Do not close an issue whose actual acceptance criteria are
   unverified.

```sh
git fetch origin develop
git worktree add --detach ../smoothcast-N origin/develop
cd ../smoothcast-N
# edit, stage named files and commit with Refs #N
git fetch origin develop && git rebase origin/develop
git push origin HEAD:develop
```

**Testing is optional for rapid develop pushes by owner instruction.**
The Verify workflow runs on explicit manual invocation; do not claim a green
test result or production guarantee without evidence. Never launch a desktop
GUI or control a receiver during routine automated work.

External contributors without push access may propose PRs targeting
`develop`. Maintainers and agents do not open topic branches or PRs.

## Version and main

`src/version.py` is the sole version authority. Increment PATCH on a
completed issue or explicit owner request, always refreshing the current
develop value before committing. Commits are not automatically merged to
`main`, tagged, published or certified. Main merges/releases are exclusively
owner-initiated manual operations.

Security issues: [SECURITY.md](SECURITY.md).
