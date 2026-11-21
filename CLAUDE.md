<!--
Maintainers: Claude Code reads this file INSTEAD of AGENTS.md when both exist,
so the import below keeps one source of truth. Put rules every agent needs in
AGENTS.md (hard limit: 2,500 characters, enforced by tests). Put only
Claude-Code-specific guidance here. Keep this file short; review both files
with `/doctor prompt-audit`. Block comments like this one are not loaded.
-->
@AGENTS.md

## Claude Code

- **Hook enforces the GUI rule.** `.claude/settings.json` runs
  `scripts/claude_hooks/block_gui_launch.py` before every Bash call and refuses
  commands that would open the real window. Do not work around it; use
  `python3 scripts/test_gui_isolated.py`.
- **`gh issue …` may fail with HTTP 403 in web sessions** (GraphQL is blocked;
  `scripts/ticket_digest.py` falls back to REST). For other issue actions use
  [REST cheat sheet](docs/agents/efficiency.md#github-cli-in-claude-code-web-sessions).
- **Plan first** (plan mode) before changing receiver or stream ownership:
  `src/cast_session.py`, `src/streamer.py`, `src/startup_cleanup.py`,
  `src/dlna.py`.
- **Subagents** only for substantial independent investigations; see
  [efficiency](docs/agents/efficiency.md).
- Personal preferences go in `CLAUDE.local.md` (gitignored).
