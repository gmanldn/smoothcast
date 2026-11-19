"""Portable M3U playlist I/O for local SmoothCast media files.

Never alter playback preferences when importing a playlist. Parsing is pure
relative to the playlist location and does not probe media or invoke GTK.
"""
from __future__ import annotations

import os
import re
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


_DIGITS = re.compile(r"(\d+)")
# S01E02 / s1.e2 / S01E02E03 (first episode wins) and the 1x02 style. The
# lookarounds stop "mix02" or "1080x1920" style names matching by accident.
_EPISODE = re.compile(
    r"(?<![a-z0-9])s(\d{1,3})[ ._-]?e(\d{1,4})(?!\d)"
    r"|(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?![a-z0-9])",
    re.IGNORECASE,
)


def natural_key(text: str) -> tuple:
    """Sort key where digit runs compare as numbers: ep2 < ep10, not ep10 < ep2."""
    return tuple(
        (0, int(part), "") if index % 2 else (1, 0, part)
        for index, part in enumerate(_DIGITS.split(str(text).casefold()))
        if part != ""
    )


def episode_of(name: str) -> tuple[int, int] | None:
    """Return (season, episode) from an SxxExx / NxNN file name, else None."""
    found = _EPISODE.search(Path(str(name)).stem)
    if found is None:
        return None
    season, episode = (found.group(1), found.group(2)) if found.group(1) else (
        found.group(3), found.group(4))
    return int(season), int(episode)


def natural_order(paths: list[str]) -> list[str]:
    """Order a batch the way people expect season/episode files to play.

    Within a folder: files with an episode marker by (season, episode), then
    the rest by natural name; folders compare naturally. Never used for M3U
    playlists, whose authored order is preserved. Stable for equal keys.
    """
    def key(path: str):
        item = Path(path)
        episode = episode_of(item.name)
        return (
            natural_key(str(item.parent)),
            (0, *episode) if episode else (1, 0, 0),
            natural_key(item.name),
            str(path),
        )
    return sorted(paths, key=key)


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
