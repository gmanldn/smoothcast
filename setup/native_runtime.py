"""Persist the native GTK runtime selected by setup, not desktop environment guesses.

The manifest lives inside the project-owned venv and is intentionally excluded
from source control. A moved native runtime is an error, never a reason to
silently use a different GTK/Python installation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

FORMAT_VERSION = 1


def manifest_path(venv: Path) -> Path:
    return venv / ".smoothcast-native-runtime.json"


def save(venv: Path, *, target: str, native_python: Path, env: dict[str, str]) -> None:
    if target not in {"linux", "macos", "windows"}:
        raise ValueError("Unknown native runtime platform")
    prefix = (env.get("SMOOTHCAST_NATIVE_PREFIX") if target == "macos"
              else env.get("MSYS2_ROOT") if target == "windows" else None)
    if target != "linux" and not prefix:
        raise ValueError("Selected native runtime prefix was not recorded")
    payload = {
        "format": FORMAT_VERSION,
        "target": target,
        "native_python": str(native_python),
        "prefix": str(Path(prefix).expanduser().resolve()) if prefix else None,
    }
    destination = manifest_path(venv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=".runtime-", delete=False,
        ) as handle:
            staged = Path(handle.name)
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        if os.name != "nt":
            staged.chmod(0o600)
        os.replace(staged, destination)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def load(venv: Path, *, target: str) -> dict[str, str | None] | None:
    path = manifest_path(venv)
    if not path.exists():
        return None  # Legacy installation; setup will write one on reinstall.
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(raw, dict) or raw.get("format") != FORMAT_VERSION
                or raw.get("target") != target
                or not isinstance(raw.get("native_python"), str)
                or not raw["native_python"]
                or (target != "linux" and (
                    not isinstance(raw.get("prefix"), str) or not raw["prefix"]))):
            raise ValueError("invalid runtime manifest")
        return raw
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            f"SmoothCast native runtime record is invalid at {path}: {exc}. "
            "Rerun the platform setup script."
        ) from exc
