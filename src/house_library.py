"""Merged house catalogue across paired nodes (#367). Pure, incremental, no IO.

Each node publishes items ``{key, title, tags?, height?, bitrate?, wired?, mtime?}``
via snapshot then monotonic-counter deltas. ``Catalogue`` groups by content_key,
lists every copy with availability, picks the best online copy, and sorts
items with no online copy last. Replaying an old delta is ignored.
"""
from __future__ import annotations


class Catalogue:
    def __init__(self, self_id: str) -> None:
        self.self_id = self_id
        self.nodes: dict[str, dict] = {}                  # node -> {name, online, counter, items{key: item}}

    def snapshot(self, node: str, name: str, items: list[dict], counter: int) -> None:
        self.nodes[node] = {"name": name, "online": True, "counter": counter,
                            "items": {i["key"]: i for i in items if i.get("key")}}

    def delta(self, node: str, counter: int, add: list[dict] = (), remove: list[str] = ()) -> bool:
        n = self.nodes.get(node)
        if n is None or counter <= n["counter"]:
            return False                                  # unknown peer (needs snapshot) or replayed/old
        for k in remove:
            n["items"].pop(k, None)
        for i in add:
            if i.get("key"):
                n["items"][i["key"]] = i
        n["counter"] = counter
        return True

    def set_online(self, node: str, online: bool) -> None:
        if node in self.nodes:
            self.nodes[node]["online"] = online

    def _copies(self, key: str) -> list[dict]:
        out = []
        for nid, n in self.nodes.items():
            it = n["items"].get(key)
            if it:
                out.append({"node": nid, "name": n["name"], "online": n["online"], "local": nid == self.self_id, "item": it})
        return out

    @staticmethod
    def _score(c: dict, max_height: int) -> tuple:
        it = c["item"]
        h = it.get("height") or 0
        fits = h <= max_height if max_height else True
        return (c["online"], c["local"], fits, h if fits else -h, bool(it.get("wired")), it.get("bitrate") or 0)

    def best_copy(self, key: str, max_height: int = 0) -> dict | None:
        copies = [c for c in self._copies(key) if c["online"]]
        return max(copies, key=lambda c: self._score(c, max_height)) if copies else None

    def entries(self, max_height: int = 0) -> list[dict]:
        keys = {k for n in self.nodes.values() for k in n["items"]}
        # merge records that share an embedded ID alias into one group
        groups: dict[str, set[str]] = {}
        alias_owner: dict[str, str] = {}
        for k in sorted(keys):
            root = k
            for n in self.nodes.values():
                it = n["items"].get(k)
                if not it:
                    continue
                for a in (it.get("tags") or {}).values():
                    root = alias_owner.setdefault(f"id:{a}", root) if a else root
            groups.setdefault(root, set()).add(k)
        rows = []
        for root, ks in groups.items():
            copies = [c for k in ks for c in self._copies(k)]
            online = [c for c in copies if c["online"]]
            best = max(online, key=lambda c: self._score(c, max_height)) if online else None
            meta = self._meta(copies)
            rows.append({"key": root, "title": meta.get("title", ""), "playable": best is not None,
                         "best": best["node"] if best else None, "best_key": best["item"]["key"] if best else None,
                         "copies": [{"node": c["node"], "name": c["name"], "online": c["online"]} for c in copies],
                         "availability": self.availability(copies)})
        return sorted(rows, key=lambda r: (not r["playable"], r["title"].lower()))

    @staticmethod
    def _meta(copies: list[dict]) -> dict:
        """Disagreement: prefer a copy with embedded tags, else the most recently modified."""
        return max((c["item"] for c in copies), key=lambda i: (bool(i.get("tags")), i.get("mtime") or 0), default={})

    @staticmethod
    def availability(copies: list[dict]) -> str:
        on = [c for c in copies if c["online"]]
        off = [c for c in copies if not c["online"]]
        if not on:
            names = ", ".join(c["name"] for c in off)
            return f"Only on {names} (offline)" if len(off) == 1 else f"On {names} (all offline)"
        first = f"On {on[0]['name']}" + "".join(f", {c['name']}" for c in on[1:])
        return first + "".join(f" · Also on {c['name']} (offline)" for c in off)
