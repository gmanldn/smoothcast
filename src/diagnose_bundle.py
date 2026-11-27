"""Redacted diagnostics bundle writer (#698 slice). Local only; nothing is uploaded.

``write_bundle`` collects versions, injected capability facts and the retained cast
attempts (already redacted by ``attempt_log``) into one JSON file the user can
review and attach. Every string passes through ``redact`` again as a last guard.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import attempt_log


def _redact_tree(value):
    if isinstance(value, str):
        return attempt_log.redact(value)
    if isinstance(value, dict):
        return {str(k): _redact_tree(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_tree(v) for v in value]
    return value


def collect(root: Path, *, app_version: str = "", capabilities: dict | None = None) -> dict:
    return _redact_tree({
        "app_version": app_version,
        "python": sys.version.split()[0],
        "platform": platform.system(),
        "capabilities": capabilities or {},
        "attempts": attempt_log.bundle(root),
    })


def write_bundle(root: Path, dest: Path, **kwargs) -> Path:
    """Write the bundle to ``dest`` (0600) and return it; the caller tells the user where it is."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(collect(Path(root), **kwargs), indent=2, sort_keys=True), encoding="utf-8")
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return dest
