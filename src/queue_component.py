"""Queue rules as a GTK-free component (ARCH-03, #691 first slice).

Owns the add / remove / clear / selection-keeping decisions that ``QueueMixin``
used to inline. It mutates the list it is given in place, so every existing
holder of ``window.queue`` keeps seeing the same object. Rendering, toasts,
persistence and the portal stay with the callers.
"""
from __future__ import annotations

import playlist_control


class QueueComponent:
    def __init__(self, paths: list[str]):
        self.paths = paths

    def add(self, new_paths: list[str]) -> list[str]:
        """Append paths not already queued (also de-duplicating within the call); return those added."""
        added: list[str] = []
        for path in new_paths:
            if path not in self.paths:
                self.paths.append(path)
                added.append(path)
        return added

    def remove(self, index: int, selected: int | None) -> tuple[str | None, int | None]:
        """Drop ``index``; return ``(removed_path, new_selected_index)``. Out of range changes nothing."""
        if not 0 <= index < len(self.paths):
            return None, selected
        removed = self.paths.pop(index)
        return removed, playlist_control.selection_after_remove(selected, index, len(self.paths))

    def clear(self) -> None:
        self.paths.clear()

    def reselect(self, selected: int | None) -> int | None:
        """Index of the previously selected path after a rebuild, or None if it is gone."""
        if selected is None or not 0 <= selected < len(self.paths):
            return None
        return selected

    def move(self, index: int, position: int, selected: int | None) -> int | None:
        """Move ``index`` to ``position``; return the selected index, which follows its path."""
        selected_path = self.paths[selected] if selected is not None and 0 <= selected < len(self.paths) else None
        self.paths.insert(position, self.paths.pop(index))
        return self.paths.index(selected_path) if selected_path in self.paths else None

    @staticmethod
    def total_duration(durations: dict[str, float], visible: list[str]) -> tuple[float, bool]:
        """Summed known duration of ``visible`` and whether every item's duration is known."""
        total = sum(durations.get(p, 0.0) or 0.0 for p in visible)
        return total, all(durations.get(p) for p in visible)

    @staticmethod
    def prune_records(records: dict, queued: set[str], keep: str | None = None) -> None:
        """Drop per-path ``records`` for paths no longer queued (``keep`` is the one extra path to retain)."""
        for path in tuple(records):
            if path not in queued and path != keep:
                records.pop(path, None)
