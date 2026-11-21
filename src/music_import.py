"""Bounded, cancellable local media discovery for explicit user imports."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import threading
from typing import Callable

import playlist_control
import streamer

MAX_ITEMS = 10_000
MAX_ENTRIES = 50_000
PROGRESS_INTERVAL = 128


@dataclass(frozen=True)
class Discovery:
    paths: tuple[str, ...]
    visited: int
    skipped: int
    truncated: bool
    cancelled: bool


def discover(
    sources: list[str | Path], *,
    extensions: set[str] | frozenset[str] = streamer.MEDIA_EXTS,
    cancel: threading.Event | None = None,
    progress: Callable[[int], None] | None = None,
    natural_sort: bool = True,
    max_items: int = MAX_ITEMS,
    max_entries: int = MAX_ENTRIES,
) -> Discovery:
    """Enumerate only explicitly selected paths, without following symlinks.

    Both the number of filesystem entries visited and returned media paths are
    bounded. Directory walking runs in a caller-owned worker; *progress* is
    called at a coarse interval and must only enqueue a UI-thread callback.
    """
    if max_items < 1 or max_entries < 1:
        raise ValueError("Discovery limits must be positive")
    allowed = {suffix.casefold() for suffix in extensions}
    pending = [Path(source).expanduser() for source in reversed(sources)]
    found: list[str] = []
    seen: set[str] = set()
    visited = skipped = 0
    truncated = cancelled = False

    def report(force: bool = False) -> None:
        if progress is not None and (force or visited % PROGRESS_INTERVAL == 0):
            progress(visited)

    while pending:
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        candidate = pending.pop()
        try:
            mode = candidate.lstat().st_mode
        except (OSError, ValueError, RuntimeError):
            skipped += 1
            visited += 1
            report()
            continue
        if stat.S_ISLNK(mode):
            skipped += 1
            visited += 1
            report()
            continue
        if stat.S_ISDIR(mode):
            try:
                with os.scandir(candidate) as entries:
                    for entry in entries:
                        if cancel is not None and cancel.is_set():
                            cancelled = True
                            break
                        if visited >= max_entries or len(found) >= max_items:
                            truncated = True
                            break
                        visited += 1
                        try:
                            if entry.is_symlink():
                                skipped += 1
                            elif entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                path = Path(entry.path)
                                if path.suffix.casefold() in allowed:
                                    identity = os.path.abspath(path)
                                    if identity not in seen:
                                        seen.add(identity)
                                        found.append(identity)
                                else:
                                    skipped += 1
                            else:
                                skipped += 1
                        except (OSError, ValueError, RuntimeError):
                            skipped += 1
                        report()
                    else:
                        continue
                if cancelled or truncated:
                    break
            except (OSError, ValueError, RuntimeError):
                skipped += 1
            continue
        visited += 1
        if stat.S_ISREG(mode) and candidate.suffix.casefold() in allowed:
            identity = os.path.abspath(candidate)
            if identity not in seen:
                seen.add(identity)
                found.append(identity)
        else:
            skipped += 1
        report()

    report(force=True)
    return Discovery(
        paths=tuple(playlist_control.natural_order(found) if natural_sort else found), visited=visited,
        skipped=skipped, truncated=truncated, cancelled=cancelled,
    )
