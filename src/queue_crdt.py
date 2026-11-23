"""Mergeable Up Next: an operation-based sequence CRDT (issue #421).

Every queue item has an immutable id and a movable fractional position key.
Operations commute and are idempotent, so replicas that saw the same set of
operations - in any order, with duplicates - show the same queue. That is what
lets a house split by a Wi-Fi outage keep editing on both sides and merge
without lost inserts. Live playback stays under the host's fenced commands.

* ``ins``  create an item (first writer of an id wins; ids are random).
* ``mov``  give an item a new key; last writer wins by (lamport, node).
* ``del``  tombstone; a delete always wins over concurrent moves.

GTK-free and clock-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import secrets
from typing import Any

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MAX_KEY = 64


def midpoint(a: str, b: str | None) -> str:
    """A key strictly between ``a`` and ``b`` (``a`` may be empty, ``b`` None = end)."""
    if b is not None:
        n = 0
        while n < len(b) and (a[n] if n < len(a) else DIGITS[0]) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + midpoint(a[n:], b[n:])
    low = DIGITS.index(a[0]) if a else 0
    high = DIGITS.index(b[0]) if b else len(DIGITS)
    if high - low > 1:
        return DIGITS[(low + high + 1) // 2 if high - low > 2 else low + 1]
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[low] + midpoint(a[1:], None)


def key_between(before: str | None, after: str | None) -> str:
    """Key for a new/moved item placed between two neighbours' keys."""
    if before is not None and after is not None and before >= after:
        raise ValueError("neighbours are out of order")
    return midpoint(before or "", after)


@dataclass
class Item:
    id: str
    key: str
    ref: Any
    by: str
    stamp: tuple[int, str]
    deleted: bool = False


@dataclass
class QueueCrdt:
    node: str
    lamport: int = 0
    items: dict[str, Item] = field(default_factory=dict)
    _pending: dict[str, list[dict]] = field(default_factory=dict)

    # -- reads ------------------------------------------------------------
    def ordered(self) -> list[Item]:
        live = [i for i in self.items.values() if not i.deleted]
        return sorted(live, key=lambda i: (i.key, i.id))

    def _neighbours(self, after_id: str | None, before_id: str | None,
                    exclude: str | None = None) -> tuple[str | None, str | None]:
        """Keys of the neighbours a new/moved item goes between.

        Concurrent inserts can leave two items with the same key (ordered by id);
        no key lies strictly between them, so the item goes just after that
        equal-key group instead, which keeps every replica convergent.
        """
        line = [i for i in self.ordered() if i.id != exclude]
        ids = [i.id for i in line]
        if after_id is not None:
            if after_id not in ids:
                raise KeyError(after_id)
            slot = ids.index(after_id) + 1
        elif before_id is not None:
            if before_id not in ids:
                raise KeyError(before_id)
            slot = ids.index(before_id)
        else:
            slot = len(line)
        before = line[slot - 1].key if slot else None
        while before is not None and slot < len(line) and line[slot].key <= before:
            slot += 1
        return before, (line[slot].key if slot < len(line) else None)

    # -- local edits (each returns the op to broadcast) -------------------
    def _tick(self) -> tuple[int, str]:
        self.lamport += 1
        return self.lamport, self.node

    def insert(self, ref: Any, *, after_id: str | None = None, before_id: str | None = None,
               by: str = "") -> dict:
        before, after = self._neighbours(after_id, before_id)
        lamport, node = self._tick()
        op = {"op": "ins", "id": secrets.token_hex(8), "key": key_between(before, after),
              "ref": ref, "by": by, "l": lamport, "n": node}
        self.apply(op)
        return op

    def move(self, item_id: str, *, after_id: str | None = None,
             before_id: str | None = None) -> dict:
        if item_id not in self.items or self.items[item_id].deleted:
            raise KeyError(item_id)
        before, after = self._neighbours(after_id, before_id, exclude=item_id)
        lamport, node = self._tick()
        op = {"op": "mov", "id": item_id, "key": key_between(before, after), "l": lamport, "n": node}
        self.apply(op)
        return op

    def delete(self, item_id: str) -> dict:
        if item_id not in self.items:
            raise KeyError(item_id)
        lamport, node = self._tick()
        op = {"op": "del", "id": item_id, "l": lamport, "n": node}
        self.apply(op)
        return op

    # -- applying (remote or local) ---------------------------------------
    def apply(self, op: dict) -> bool:
        """Apply one operation; idempotent. Returns True if it changed anything."""
        kind, item_id = op["op"], op["id"]
        self.lamport = max(self.lamport, int(op["l"]))
        stamp = (int(op["l"]), str(op["n"]))
        if kind == "ins":
            if item_id in self.items:
                return False
            if not isinstance(op["key"], str) or not 0 < len(op["key"]) <= MAX_KEY:
                return False
            self.items[item_id] = Item(item_id, op["key"], op["ref"], str(op.get("by", "")), stamp)
            for waiting in sorted(self._pending.pop(item_id, []), key=lambda o: (o["l"], o["n"])):
                self.apply(waiting)
            return True
        item = self.items.get(item_id)
        if item is None:                      # arrived before its insert: hold it
            bucket = self._pending.setdefault(item_id, [])
            if op not in bucket:
                bucket.append(op)
            return False
        if kind == "del":
            changed = not item.deleted
            item.deleted = True
            return changed
        if kind == "mov":
            if item.deleted or stamp <= item.stamp or not 0 < len(op["key"]) <= MAX_KEY:
                return False
            item.key, item.stamp = op["key"], stamp
            return True
        return False
