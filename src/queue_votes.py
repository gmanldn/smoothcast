"""One-person-one-vote ordering for waiting queue items (#326): pure and bounded.

A voter (room participant id) holds at most one vote per item; re-posting the
same vote is idempotent. ``order`` re-sorts only the *waiting* items: the item
at ``playing_id`` and anything pinned never move, and ties keep insertion order,
so a vote can never skip the current film or thrash equal items.
"""
from __future__ import annotations

MAX_VOTERS_PER_ITEM = 64
MAX_ITEMS = 500


class Votes:
    def __init__(self) -> None:
        self._by_item: dict[str, set[str]] = {}

    def vote(self, item_id: str, voter: str, on: bool = True, *, active: set[str] | None = None) -> bool:
        """Set voter's vote; False when rejected (revoked voter, bad ids, or bounds)."""
        if not isinstance(item_id, str) or not isinstance(voter, str) or not item_id or not voter:
            return False
        if active is not None and voter not in active:
            return False
        voters = self._by_item.get(item_id)
        if not on:
            if voters:
                voters.discard(voter)
            return True
        if voters is None:
            if len(self._by_item) >= MAX_ITEMS:
                return False
            voters = self._by_item[item_id] = set()
        if voter not in voters and len(voters) >= MAX_VOTERS_PER_ITEM:
            return False
        voters.add(voter)
        return True

    def count(self, item_id: str, active: set[str] | None = None) -> int:
        voters = self._by_item.get(item_id, set())
        return len(voters if active is None else voters & active)

    def voted(self, item_id: str, voter: str) -> bool:
        return voter in self._by_item.get(item_id, ())

    def forget(self, keep_ids: set[str]) -> None:
        """Drop votes for items no longer queued."""
        for item_id in [i for i in self._by_item if i not in keep_ids]:
            del self._by_item[item_id]

    def order(self, queue_ids: list[str], playing_id: str | None = None,
              pinned: set[str] | None = None, active: set[str] | None = None) -> list[str]:
        """Queue order with waiting, unpinned items sorted by votes (stable on ties)."""
        pinned = pinned or set()
        fixed = {i for i in queue_ids if i == playing_id or i in pinned}
        movable = [i for i in queue_ids if i not in fixed]
        ranked = iter(sorted(movable, key=lambda i: -self.count(i, active)))  # sorted() is stable
        return [i if i in fixed else next(ranked) for i in queue_ids]
