"""GTK-free, ownership-safe queue-duration probing.

Probe file metadata off-thread using a supplied function. Applying the
result to queue state is the caller's responsibility on the GTK main loop.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaProbe:
    fingerprint: tuple[int, int, int, int, int] | None
    media: object | None


def file_fingerprint(path: str | Path) -> tuple[int, int, int, int, int] | None:
    """Identity for cached metadata; missing files never produce reusable data."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def cached_media(cache: Mapping[str, tuple], path: str | Path) -> object | None:
    """Return cached media only while the source file has the same identity."""
    entry = cache.get(str(path))
    fingerprint = file_fingerprint(path)
    if fingerprint is None or not entry or len(entry) != 2 or entry[0] != fingerprint:
        return None
    return entry[1]


def media_title(path: str | Path, media: object | None = None,
                display_name: str | None = None, *, fallback: str | None = None) -> str:
    """Use verified tags and original contribution names, never an absolute path."""
    name = display_name.strip() if isinstance(display_name, str) else ""
    title = str(getattr(media, "title", "") or "").strip() or name or fallback or Path(path).name
    artist = str(getattr(media, "artist", "") or "").strip()
    album = str(getattr(media, "album", "") or "").strip()
    value = f"{artist} — {title}" if artist else title
    return f"{value} · {album}" if album else value


def display_title(path: str | Path, cache: Mapping[str, tuple],
                  display_name: str | None = None) -> str:
    """Format verified embedded tags and the original contribution name."""
    return media_title(path, cached_media(cache, path), display_name)


def media_for_cast(
    entry: tuple | None, path: str | Path, probe: Callable[[Path], object],
) -> tuple[object, tuple[int, int, int, int, int] | None]:
    """Use a snapshot only while the source still has its cached identity."""
    fingerprint = file_fingerprint(path)
    if fingerprint is not None and entry is not None and len(entry) == 2 and entry[0] == fingerprint:
        return entry[1], fingerprint
    return probe(Path(path)), None


def inspect_media(
    paths: Iterable[str],
    probe: Callable[[str], object],
    *,
    cancelled=None,
) -> dict[str, MediaProbe]:
    """Probe cancellably and retain results only if the source did not change."""
    results: dict[str, MediaProbe] = {}
    for path in paths:
        if cancelled is not None and cancelled.is_set():
            break
        fingerprint = file_fingerprint(path)
        if fingerprint is None:
            results[path] = MediaProbe(None, None)
            continue
        try:
            media = probe(path)
        except Exception:
            results[path] = MediaProbe(fingerprint, None)
            continue
        if (cancelled is not None and cancelled.is_set()) or file_fingerprint(path) != fingerprint:
            continue
        results[path] = MediaProbe(fingerprint, media)
    return results


def publish_media(
    cache: dict[str, tuple],
    queued_paths: Iterable[str],
    results: Mapping[str, MediaProbe],
    *,
    max_entries: int = 64,
) -> None:
    """Publish valid queue metadata on the caller thread with a bounded cache."""
    active = set(queued_paths)
    for path, result in results.items():
        if (path in active and result.media is not None and result.fingerprint is not None
                and result.fingerprint == file_fingerprint(path)):
            cache[path] = (result.fingerprint, result.media)
    while len(cache) > max_entries:
        del cache[next(iter(cache))]


def inspect(paths: Iterable[str], probe: Callable[[str], float]) -> dict[str, float]:
    """Return independent results without reading or mutating GUI state."""
    durations: dict[str, float] = {}
    for path in paths:
        try:
            durations[path] = probe(path)
        except Exception:
            # A corrupt or missing film must not prevent the other queue items
            # from receiving a duration. Existing zero-duration semantics.
            durations[path] = 0.0
    return durations


def publish(
    cache: dict[str, float],
    queued_paths: Iterable[str],
    results: Mapping[str, float],
) -> None:
    """Publish only still-queued files without overwriting newer probes."""
    active = set(queued_paths)
    for path, duration in results.items():
        if path in active:
            cache.setdefault(path, duration)
