---
description: Bounded SmoothCast GitHub issue digest and next-ticket workflow
---

Use the canonical read-only index; do not download the whole backlog.

1. Run `python3 scripts/ticket_digest.py --next` for the highest-priority
   unclaimed issue. Use `--priority P0`, `--label` or `--limit` to narrow it.
2. If the user supplied an issue number, run
   `python3 scripts/ticket_digest.py --show <number>`; add `--comments` only
   when ownership or prior evidence matters.
3. Read the fast path in `docs/ISSUES.md`. Claim by assigning yourself and
   posting one short comment. Work in an isolated worktree and issue branch
   targeting `develop` (`main` is protected and release-only).
4. Validate targeted tests first, then the full headless suite when warranted.
   Never launch or focus the real GTK app.
5. Close only with compact evidence and completed acceptance checks; use
   `Refs #N` and leave the issue open when device qualification remains.
