"""Commands and private child dispatch for a PyInstaller-frozen SmoothCast.

In a bundle sys.executable is SmoothCast, NOT a Python interpreter. Never
pass source .py paths to it or fall back to an ambient catt installation.
Helper flags are only intercepted when the current process is frozen.
"""
from __future__ import annotations

from pathlib import Path
import sys

SERVER_FLAG = "--_smoothcast-hls-server"
CATT_FLAG = "--_smoothcast-catt"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def server_command(source_script: Path) -> list[str]:
    if is_frozen():
        return [sys.executable, SERVER_FLAG]
    return [sys.executable, str(source_script)]


def catt_command(external_binary: str, args: list[str]) -> list[str]:
    if is_frozen():
        return [sys.executable, CATT_FLAG, *args]
    return [external_binary, *args]


def dispatch_frozen_helper(args: list[str]) -> int | None:
    """Handle only our frozen subprocess roles; ordinary CLI remains unchanged."""
    if not is_frozen() or not args:
        return None
    if args[0] == SERVER_FLAG:
        if len(args) != 1:
            return 2
        from server import main as serve
        serve()
        return 0
    if args[0] == CATT_FLAG:
        from catt.cli import main as catt_main

        original = sys.argv
        try:
            # CATT's Click entry point reads sys.argv itself.
            sys.argv = ["catt", *args[1:]]
            result = catt_main()
        finally:
            sys.argv = original
        return result if isinstance(result, int) else 0
    return None
