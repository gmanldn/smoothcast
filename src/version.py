"""SmoothCast's single authoritative semantic release version.

Change MAJOR/MINOR/PATCH exactly once per release. Ordinary Git commits between
releases are identified by their commit SHA, not fictitious per-commit versions.
The running Python process keeps its imported version even if an asynchronous
git pull changes the on-disk checkout; restarting loads the new version.
"""
from __future__ import annotations

import ast
from pathlib import Path

MAJOR = 1
MINOR = 2
PATCH = 0

__version__ = f"{MAJOR}.{MINOR}.{PATCH}"


def label() -> str:
    """Canonical human-readable version for CLI and GTK: vMAJOR.MINOR.PATCH."""
    return f"v{__version__}"


def read_checkout_version(path: Path) -> str | None:
    """Read a newer on-disk version.py *without executing it*.

    Only top-level integer assignments of MAJOR, MINOR and PATCH are accepted.
    This intentionally cannot mutate the imported/runtime version.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError, ValueError):
        return None
    parts: dict[str, int] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        name = statement.targets[0].id
        value = statement.value
        if name in {"MAJOR", "MINOR", "PATCH"} and isinstance(value, ast.Constant):
            if type(value.value) is int and value.value >= 0:
                parts[name] = value.value
    if set(parts) != {"MAJOR", "MINOR", "PATCH"}:
        return None
    return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['PATCH']}"


if __name__ == "__main__":
    print(f"SmoothCast {label()}")