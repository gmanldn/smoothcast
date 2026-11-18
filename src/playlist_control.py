"""Portable M3U playlist I/O for local SmoothCast media files.

Never alter playback preferences when importing a playlist. Parsing is pure
relative to the playlist location and does not probe media or invoke GTK.
"""
from __future__ import annotations

import os
from pathlib import Path


class PlaylistError(ValueError):
    """Unable to read or save a local playlist."""


def load_playlist(path: Path) -> tuple[list[str], int]:
    """Return (unique existing local paths, skipped entries) from an M3U.

    Resolve relative entries against the playlist directory, not the current
    working directory. Ignore metadata/comments, non-local URLs and missing
    entries. Bound parsing size to avoid hanging the GTK event loop.
    """
    path = Path(path).expanduser()
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise PlaylistError("Playlist is too large (maximum 4 MiB)")
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except PlaylistError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PlaylistError(f"Cannot read playlist: {exc}") from exc

    result: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for raw in lines:
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        if "://" in entry or "\0" in entry:
            skipped += 1
            continue
        candidate = Path(entry).expanduser()
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        try:
            candidate = candidate.resolve()
            if not candidate.is_file():
                skipped += 1
                continue
        except (OSError, ValueError):
            skipped += 1
            continue
        normalized = str(candidate)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result, skipped


def save_playlist(path: Path, items: list[str]) -> None:
    """Atomically save a local M3U playlist so interrupted writes cannot lose it."""
    if not items:
        raise PlaylistError("Queue is empty")
    path = Path(path).expanduser()
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    data = "#EXTM3U\n" + "".join(str(Path(p).expanduser().resolve()) + "\n" for p in items)
    try:
        temp.write_text(data, encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        raise PlaylistError(f"Cannot save playlist: {exc}") from exc
    finally:
        temp.unlink(missing_ok=True)


def matches_query(path: str, query: str) -> bool:
    """Filter a queue by case-insensitive filename/folder terms, in any order."""
    haystack = str(path).casefold()
    return all(term in haystack for term in str(query).casefold().split())
