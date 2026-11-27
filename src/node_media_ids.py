"""Per-item sharing with scoped, expiring media ids for paired nodes (#355). Pure.

Only items the host explicitly shared get an id. An id is an HMAC over
(item, peer, expiry) so it works for exactly one peer, expires, and dies when
the item is unshared or the peer is revoked. Nothing here carries a path or URL.
"""
from __future__ import annotations

import hashlib
import hmac

DEFAULT_TTL_S = 3600.0


class SharedMedia:
    def __init__(self, secret: bytes) -> None:
        self._secret = secret
        self._items: dict[str, str] = {}      # item_key -> local ref (host-side only)
        self._revoked_peers: set[str] = set()

    def share(self, item_key: str, local_ref: str) -> None:
        self._items[item_key] = local_ref

    def unshare(self, item_key: str) -> None:
        self._items.pop(item_key, None)

    def revoke_peer(self, peer: str) -> None:
        self._revoked_peers.add(peer)

    def _sig(self, item_key: str, peer: str, expires: int) -> str:
        return hmac.new(self._secret, f"{item_key}|{peer}|{expires}".encode(), hashlib.sha256).hexdigest()[:24]

    def issue(self, item_key: str, peer: str, now: float, ttl: float = DEFAULT_TTL_S) -> str | None:
        if item_key not in self._items or peer in self._revoked_peers:
            return None
        expires = int(now + max(1.0, min(ttl, 24 * 3600.0)))
        return f"{item_key}.{expires}.{self._sig(item_key, peer, expires)}"

    def resolve(self, media_id: str, peer: str, now: float) -> tuple[str | None, str]:
        """(local_ref, "") for the host to open, or (None, reason). Never trusts a client path."""
        try:
            item_key, exp, sig = media_id.rsplit(".", 2)
            expires = int(exp)
        except (ValueError, AttributeError):
            return None, "Invalid media id."
        if peer in self._revoked_peers:
            return None, "Device was revoked."
        if not hmac.compare_digest(sig, self._sig(item_key, peer, expires)):
            return None, "Invalid media id."
        if now > expires:
            return None, "Link expired. Ask again."
        ref = self._items.get(item_key)
        return (ref, "") if ref else (None, "That item is no longer shared.")
