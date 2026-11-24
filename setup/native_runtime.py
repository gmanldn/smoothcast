"""Persist the native GTK runtime selected by setup, not desktop environment guesses.

The manifest lives inside the project-owned venv and is intentionally excluded
from source control. A moved native runtime is an error, never a reason to
silently use a different GTK/Python installation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile

FORMAT_VERSION = 1
MAX_MANIFEST_BYTES = 128 * 1024


def manifest_path(venv: Path) -> Path:
    return venv / ".smoothcast-native-runtime.json"


def _absolute_path(value: object) -> bool:
    return isinstance(value, str) and "\x00" not in value and Path(value).is_absolute()


def save(venv: Path, *, target: str, native_python: Path, env: dict[str, str]) -> None:
    if target not in {"linux", "macos", "windows"}:
        raise ValueError("Unknown native runtime platform")
    if not _absolute_path(str(native_python)):
        raise ValueError("Selected native Python must have an absolute path")
    prefix = (env.get("SMOOTHCAST_NATIVE_PREFIX") if target == "macos"
              else env.get("MSYS2_ROOT") if target == "windows" else None)
    if target != "linux" and not _absolute_path(prefix):
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
    try:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return None  # Legacy installation; setup writes one on reinstall.
        if not stat.S_ISREG(mode):
            raise ValueError("runtime manifest must be an ordinary file")
        with path.open("rb") as handle:
            data = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise ValueError("runtime manifest is too large")
        raw = json.loads(data.decode("utf-8"))
        if (not isinstance(raw, dict) or type(raw.get("format")) is not int
                or raw["format"] != FORMAT_VERSION or raw.get("target") != target
                or not _absolute_path(raw.get("native_python"))
                or (target != "linux" and not _absolute_path(raw.get("prefix")))):
            raise ValueError("invalid runtime manifest")
        return raw
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        raise RuntimeError(
            f"SmoothCast native runtime record is invalid at {path}: {exc}. "
            "Rerun the platform setup script."
        ) from exc
