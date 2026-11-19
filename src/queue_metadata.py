"""GTK-free, ownership-safe queue-duration probing.

Probe file metadata off-thread using a supplied function. Applying the
result to queue state is the caller's responsibility on the GTK main loop.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping


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
