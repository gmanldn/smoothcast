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
    path = Path(path).expanduser().resolve()
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    entries: list[str] = []
    for item in items:
        # M3U is line-oriented: a newline in one source path would inject
        # an unrelated queued item into the exported playlist.
        if any(char in str(item) for char in ("\n", "\r", "\0")):
            raise PlaylistError("Media path contains an invalid line or null character")
        media = Path(item).expanduser().resolve()
        try:
            # Relocating a playlist and its sibling media tree should preserve
            # playback order without hand-editing paths.
            entry = os.path.relpath(media, path.parent)
        except ValueError:
            # On Windows, relpath across different drive letters is invalid.
            # Preserve an absolute path rather than failing to save the queue.
            entry = str(media)
        entries.append(entry)
    data = "#EXTM3U\n" + "".join(entry + "\n" for entry in entries)
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


def selection_after_move(selected: int | None, source: int, target: int) -> int | None:
    """Track the selected media identity when two queue entries swap."""
    if selected == source:
        return target
    if selected == target:
        return source
    return selected


def selection_after_remove(
    selected: int | None, removed: int, remaining: int,
) -> int | None:
    """Keep the selected file, or select a neighbour when it is removed."""
    if selected is None or remaining <= 0:
        return None
    if selected == removed:
        return min(removed, remaining - 1)
    return selected - 1 if selected > removed else selected
