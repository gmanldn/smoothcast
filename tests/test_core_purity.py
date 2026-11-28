"""Core purity ratchet (ARCH-02, #690): pure-domain modules stay free of GTK, subprocess and sockets.

``CORE`` lists modules that are pure today. Add a module when you make it pure;
removing one needs a reason in the commit. Only import-time imports count.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
BANNED = {"gi", "subprocess", "socket", "socketserver", "http", "urllib", "asyncio", "ssl"}
CORE = [
    "action_state", "api_spec", "audio_delay", "hw_encoder_state", "paths", "picture_adjustments",
    "playback_state", "room_layout", "store", "settings", "stream_health", "subtitle_style",
    "ui_tokens", "shutdown_plan", "errors", "settings_catalog",
]


def _imports(path: Path) -> set[str]:
    found: set[str] = set()

    def visit(body):
        for node in body:
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                visit(node.body)
                visit(node.orelse)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def test_core_modules_import_no_gtk_process_or_network():
    bad = {}
    for name in CORE:
        hit = _imports(SRC / f"{name}.py") & BANNED
        if hit:
            bad[name] = sorted(hit)
    assert not bad, f"core module(s) must stay pure: {bad}"
