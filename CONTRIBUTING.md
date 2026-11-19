# Contributing to SmoothCast

**GitHub Issues are the only backlog.** Read [docs/ISSUES.md](docs/ISSUES.md)
for the claim → implement → validate → close workflow and
[AGENTS.md](AGENTS.md) for repository rules; do not add a parallel Markdown
feature list.

1. Find or open an issue (use the template). Claim it with a comment before
   starting, and work on a branch off `develop`.
2. Open pull requests against **`develop`**. `main` is protected and
   release-only.
3. Test headlessly — never launch the real GUI or control a TV in routine tests:

   ```sh
   python3 -m pytest -q tests
   python3 -m compileall -q src scripts setup tests
   ruff check src scripts setup tests
   ```

   Optional pre-commit hooks: `pip install pre-commit && pre-commit install`.
   An explicit GUI smoke test lives in `scripts/test_gui_isolated.py` (private
   Xvfb only). See [docs/agents/testing.md](docs/agents/testing.md).
4. Use `Fixes #N` only when every acceptance item passes; use `Refs #N` if real
   device verification is still pending.

Security issues: see [SECURITY.md](SECURITY.md).
