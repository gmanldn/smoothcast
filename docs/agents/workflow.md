# Agent workflow — tickets, code, releases

**Source of truth:** [docs/ISSUES.md](../ISSUES.md) and
[GitHub Issues](https://github.com/gmanldn/smoothcast/issues).
The retired root `IMPROVEMENTS.md` is **not** an active backlog.

## Branch model

- `develop` is the integration branch: every issue branch and pull request
  targets `develop`.
- `main` is **protected** and release-only. It receives release merges from
  `develop`; never push to it directly and never open a feature PR against it.
- `src/version.py` is bumped on `develop` at a release boundary; promoting
  `develop` into `main` publishes that release.

1. Read the relevant GitHub issue and its acceptance criteria first; check
   related PRs, existing implementation and relevant logs. Prioritise P0/P1.
2. **claim the issue** in a comment before work; avoid duplicating another
   agent's active task. Use an isolated branch/worktree off `develop`, never
   the shared checkout.
3. Locate the changed symbols, callers and tests. Choose a minimal **complete**
   fix; reuse helpers and standard library where sensible. Preserve validation,
   casting ownership, accessibility, existing behaviour and diagnostics.
4. Add/adjust focused regression tests, run relevant headless tests, then
   full headless verification where feasible. Never open the real GUI to test.
5. Commit and push coherent changes frequently; link the issue and PR with
   tests run, evidence, limitations and outstanding real-device validation.
6. Only close a ticket when **all** acceptance criteria are supported, including
   TV/platform tests when required. Never equate CI success with hardware
   verification. Avoid deleting existing tickets or losing original research.

**Identifier caveat:** `[P0][SC-058]` contains a legacy issue ID; `SC-058`
is **not** GitHub issue `#58`. Resolve the current GitHub issue by search.

**Protect the user's work:** don't discard dirty files, local commits, stashes,
or unmerged branches; never force-reset without explicit permission. A
diverged checkout requires backup/reconciliation, not `git reset --hard`.

**Version authority:** `src/version.py` only. Bump semantic versions at an
intentional release boundary, **not** for each commit. Distinguish loaded
runtime release, on-disk version and Git SHA in diagnostics.
`./smoothcast --version` is safe: it does not open GTK.

Use `git diff --stat` and targeted file ranges first. Avoid entire repository
or log dumps by default; preserve and surface exact failed traces when needed.
