"""Private, conservative persistence for a shared room's queue only."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import json
import os
from pathlib import Path
import stat
from typing import Iterable

import cache_privacy


SCHEMA_VERSION = 1
MAX_ITEMS = 1000
MAX_PATH_CHARS = 4096
MAX_CHECKPOINT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class LoadResult:
    items: tuple[str, ...] = ()
    unavailable: int = 0
    error: str | None = None


def write_checkpoint(path: Path, items: Iterable[str]) -> None:
    """Atomically save queue order without session or participant credentials."""
    values = list(islice(items, MAX_ITEMS + 1))
    if len(values) > MAX_ITEMS:
        raise ValueError(f"Room queue exceeds the {MAX_ITEMS} item checkpoint limit")
    if any(not isinstance(item, str) or not item or len(item) > MAX_PATH_CHARS
           or "\x00" in item or not Path(item).is_absolute()
           for item in values):
        raise ValueError("Room queue checkpoint accepts absolute local file paths only")
    payload = {"schema_version": SCHEMA_VERSION, "items": values}
    # Match the private writer's JSON encoding before replacing the last
    # readable checkpoint: escaped Unicode may be much larger than its path.
    if len(json.dumps(payload).encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Checkpoint is larger than the supported limit")
    cache_privacy.write_private_json_atomic(path, payload)


def load_checkpoint(path: Path) -> LoadResult:
    """Read a private checkpoint and retain only currently readable files."""
    if not path.exists():
        return LoadResult()
    try:
        cache_privacy.ensure_private_directory(path.parent)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                return LoadResult(error="Checkpoint is not a regular file")
            if os.name != "nt":
                if metadata.st_uid != os.getuid():
                    return LoadResult(error="Checkpoint belongs to another user")
                if stat.S_IMODE(metadata.st_mode) != 0o600:
                    os.fchmod(descriptor, 0o600)
            if metadata.st_size > MAX_CHECKPOINT_BYTES:
                return LoadResult(error="Checkpoint is larger than the supported limit")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                content = stream.read(MAX_CHECKPOINT_BYTES + 1)
            if len(content) > MAX_CHECKPOINT_BYTES:
                return LoadResult(error="Checkpoint is larger than the supported limit")
            payload = json.loads(content.decode("utf-8"))
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileNotFoundError:
        return LoadResult()
    except (OSError, ValueError, RecursionError):
        return LoadResult(error="Checkpoint could not be read")

    if (not isinstance(payload, dict)
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != SCHEMA_VERSION):
        return LoadResult(error="Checkpoint version is unsupported")
    values = payload.get("items")
    if not isinstance(values, list) or len(values) > MAX_ITEMS:
        return LoadResult(error="Checkpoint queue is invalid")

    restored: list[str] = []
    unavailable = 0
    for value in values:
        if (not isinstance(value, str) or not value
                or len(value) > MAX_PATH_CHARS or "\x00" in value
                or not Path(value).is_absolute()):
            unavailable += 1
            continue
        try:
            media = Path(value)
            # Progressive or interrupted uploads can still exist as regular
            # files. A restart has no completion record for a .partial file.
            if media.resolve().suffix.lower() == ".partial":
                unavailable += 1
                continue
            metadata = media.stat()
            if not stat.S_ISREG(metadata.st_mode) or not os.access(media, os.R_OK):
                unavailable += 1
                continue
        except (OSError, RuntimeError, ValueError):
            unavailable += 1
            continue
        restored.append(value)
    return LoadResult(tuple(restored), unavailable)
