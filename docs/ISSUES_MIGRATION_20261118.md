# SmoothCast issue migration — 18 November 2026

This is **historical provenance**, not a work queue. The authoritative
workflow is [ISSUES.md](ISSUES.md); the only live backlog is
[SmoothCast GitHub Issues](https://github.com/gmanldn/smoothcast/issues).

## Migration and evidence

- The prior `IMPROVEMENTS.md` contained **132 numbered proposals**:
  original compatibility/development proposals 1–50; later bug-and-reliability
  audit 51–100; and original player features recovered as 101–132.
- **All 132 have their own canonical GitHub issue**, with the stable
  `SC-001`–`SC-132` identifiers and the original acceptance requirement
  copied into the body. Items with prior implementation notes retain those
  notes; they remain open until any unverified acceptance work is completed.
- The migration source is an immutable
  [pre-deletion Git revision](https://github.com/gmanldn/smoothcast/blob/b76579c12f6a202188cc7964a0de06c09bd5aa9e/IMPROVEMENTS.md).
  The original 50-item player list (including *historical*, not revalidated
  completion marks) also survives verbatim under
  [IMPROVEMENTS_ORIGINAL_50_20261118.md](IMPROVEMENTS_ORIGINAL_50_20261118.md).
- The migration generated two duplicate issues
  [#28](https://github.com/gmanldn/smoothcast/issues/28) and
  [#29](https://github.com/gmanldn/smoothcast/issues/29), both closed with
  a redirect to canonical [#26](https://github.com/gmanldn/smoothcast/issues/26)
  (`SC-019`) and [#27](https://github.com/gmanldn/smoothcast/issues/27)
  (`SC-020`). They are **not** additional backlog items.
- No uncommitted local material was included. If a paid research batch or
  user changes exist only in a local stash, backup or worktree, preserve
  them and create **new issues for genuinely new proposals**, referencing
  their provenance. Never overwrite or replace existing issues wholesale.

## Verification rule

For migration verification use the canonical IDs `SC-001` through `SC-132`;
each must resolve to exactly one *open or completed* primary issue. The closed
migration duplicates #28/#29 are excluded. Every proposal must remain
discoverable in a GitHub issue or an explicitly linked, closed duplicate;
never recreate the removed Markdown backlog as a second authority.

If GitHub Issues is temporarily unavailable, commit a repair or document the
blocker on a branch and reconcile it with the original issue when access
returns. Do not silently start a second permanent issue store.
