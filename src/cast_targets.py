"""Pure ordering for the receiver picker: pin favourites, then most-recently-used.

Discovered and manual targets are merged without duplicates. Pinned receivers
come first; within each group the most recently successful session sorts first.
Discovery order is preserved for equal keys, so a cold start keeps the LAN scan
order. No GTK and no I/O here.
"""
from __future__ import annotations


def ordered_names(
    discovered: list[str], manual: list[str], favourites: list[str],
    last_used: dict | None,
) -> list[str]:
    """Return unique target names: pinned first, then most recently used."""
    names = list(dict.fromkeys(
        list(discovered) + [m for m in manual if isinstance(m, str)]
    ))
    pinned = set(favourites)
    recent = last_used or {}

    def key(name: str):
        try:
            used = float(recent.get(name, 0.0))
        except (TypeError, ValueError):
            used = 0.0
        return (0 if name in pinned else 1, -used)

    return sorted(names, key=key)


def record_use(last_used: dict | None, name: str, now: float, *, limit: int = 32) -> dict:
    """Return a bounded copy of *last_used* with *name* marked used at *now*."""
    updated = {
        key: float(value) for key, value in (last_used or {}).items()
        if isinstance(key, str) and isinstance(value, (int, float))
    }
    updated[str(name)] = float(now)
    if len(updated) > limit:
        oldest = sorted(updated, key=updated.get)[:len(updated) - limit]
        for key in oldest:
            updated.pop(key, None)
    return updated


def is_manual(name: str, manual: list[str]) -> bool:
    """True when *name* is a user-entered manual target, not a discovery."""
    return name in set(m for m in manual if isinstance(m, str))


NO_SELECTION = 2 ** 32 - 1  # Gtk.INVALID_LIST_POSITION


def select_index(names: list[str], device: str) -> int:
    """Index of *device* in *names*, adding a saved one; NO_SELECTION if unset (#239)."""
    if device and device not in names:
        names.insert(0, device)
    return names.index(device) if device in names else NO_SELECTION
