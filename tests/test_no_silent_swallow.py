"""Ratchet: no new silent ``except: pass`` on playback paths (#207).

Each playback module keeps the handlers it has today (best-effort cleanup of
sockets, temp files and child processes). A *new* handler whose whole body is
``pass`` fails here: handle it with a catalogued code, log it, or narrow it. If
you removed one, lower the number. The counts only go down.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Allow-list: best-effort cleanup where failure is genuinely harmless.
ALLOWED = {
    "cast_session.py": 3, "streamer.py": 9, "dlna.py": 4, "castctl.py": 1,
    "cast_av.py": 0, "preflight.py": 0, "ffmpeg_compat.py": 0,
}


def silent_handlers(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(1 for node in ast.walk(tree)
               if isinstance(node, ast.ExceptHandler)
               and all(isinstance(stmt, ast.Pass) for stmt in node.body))


def test_no_new_silent_exception_swallowing_on_playback_paths():
    found = {name: silent_handlers(ROOT / "src" / name) for name in ALLOWED}
    worse = {n: (found[n], limit) for n, limit in ALLOWED.items() if found[n] > limit}
    assert not worse, f"new silent `except: pass` (found, allowed): {worse}"


def test_allow_list_shrinks_with_the_code():
    found = {name: silent_handlers(ROOT / "src" / name) for name in ALLOWED}
    stale = {n: (found[n], limit) for n, limit in ALLOWED.items() if found[n] < limit}
    assert not stale, f"lower ALLOWED so the ratchet keeps tightening: {stale}"
