# Contributing to SmoothCast

**`develop` is the only branch anyone commits to.** `main` is release-only: it
is updated automatically by a develop→main pull request when a verified
`develop` commit bumps `src/version.py`. Never commit or push to `main`.

**GitHub Issues are the only backlog.** Read [docs/ISSUES.md](docs/ISSUES.md)
for the claim → implement → validate → close workflow and
[AGENTS.md](AGENTS.md) / [docs/agents/workflow.md](docs/agents/workflow.md)
for the repository rules; do not add a parallel Markdown feature list.

## Maintainers and agents (push access)

1. Claim an issue with a comment before starting.
2. Work in a detached worktree of `origin/develop`, never the shared checkout:

   ```sh
   git fetch origin
   git worktree add --detach ../smoothcast-N origin/develop
   ```

3. Check headlessly — never launch the real GUI or control a TV. Patch work
   uses the fast lane; the full suite is required only for MINOR/MAJOR bumps:

   ```sh
   python3 -m compileall -q src scripts setup tests
   python3 -m py_compile smoothcast
   ruff check src scripts setup tests smoothcast setup.py
   mypy
   python3 -m pytest -q tests -n auto   # MINOR/MAJOR only
   ```

   `python3 scripts/ci/test_scope.py --base origin/develop` reports the lane CI
   will use. Target tests for changed behavior during patch work.

4. Commit small and coherent (`Refs #N`), integrate with
   `git fetch origin && git rebase origin/develop` (your unpushed commits only),
   re-test, and `git push origin HEAD:develop`. Never force-push.
5. Keep `develop` green: if CI goes red, fix it or `git revert` it first.
6. Remove the worktree when done. Close an issue only when every acceptance
   item passes; use `Refs #N` if real-device verification is pending.

Optional local guard: `pip install pre-commit && pre-commit install` (Ruff,
compileall, and a hook that refuses commits on `main`).

## External contributors (no push access)

Fork, branch, and open a pull request **against `develop`**.

## Releases

`python3 scripts/ci/bump_version.py` on `develop`, push, and the release
reaches `main` automatically once CI verifies it. Patch bumps use the fast
lane; MINOR/MAJOR bumps run the full test matrix. Publishing a GitHub release
is a separate tag step: see [docs/agents/workflow.md](docs/agents/workflow.md).

Security issues: see [SECURITY.md](SECURITY.md).
