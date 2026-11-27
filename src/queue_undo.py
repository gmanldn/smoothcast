"""Host undo for the last safe queue edit (#328). Pure, in-memory, bounded.

Only add/remove/move are recorded. ``undo`` applies the inverse to a queue of
item ids only if the queue is exactly the state the edit produced (revision
match) and the needed media still exists; otherwise it rejects without
touching anything. The playing item is never changed, and each entry can be
consumed once, so a replayed Undo cannot apply twice.
"""
from __future__ import annotations

MAX_HISTORY = 20


class UndoLog:
    def __init__(self) -> None:
        self._log: list[dict] = []

    def record(self, op: str, item: str, before: list[str], after: list[str],
               revision: int, actor: str = "", payload: object = None) -> None:
        if op not in ("add", "remove", "move") or before == after:
            return
        self._log.append({"op": op, "item": item, "before": list(before), "after": list(after),
                          "revision": revision, "actor": actor, "payload": payload})
        del self._log[:-MAX_HISTORY]

    def clear(self) -> None:
        self._log.clear()

    def undo(self, queue: list[str], revision: int, playing: str | None = None,
             available: set[str] | None = None) -> tuple[list[str] | None, str]:
        """Return (new_queue, "") on success or (None, reason) without side effects."""
        if not self._log:
            return None, "Nothing to undo."
        entry = self._log[-1]
        if entry["revision"] != revision or queue != entry["after"]:
            return None, "The queue changed since that edit."
        target = entry["before"]
        if playing is not None and (playing in queue) != (playing in target) and entry["item"] == playing:
            return None, "That item is playing now."
        if available is not None:
            missing = [i for i in target if i not in queue and i not in available]
            if missing:
                return None, "That media is no longer available."
        self._log.pop()                      # consume: a replay finds the next entry or nothing
        return list(target), ""
