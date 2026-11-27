"""Mergeable Up Next queue: a fractional-key sequence CRDT (#421). Pure, no I/O.

State: {"items": {id: {key, ref, by, at, deleted, ks}}, "clock": n}. Order = sort by (key, id).
Op: {op:'ins'|'mov'|'del', id, key?, ref?, lamport, node}. Ops are idempotent and commute; ``merge`` is a
per-item join (ref once, deleted OR, key by highest (lamport,node)). A delete is a permanent tombstone, so
move+delete -> delete wins. Playback state is NOT replicated here.
"""
from __future__ import annotations

import re

MAX_ITEMS, MAX_KEY = 500, 32
_KEY = re.compile(r"[a-z]{1,64}\Z")
_ID = re.compile(r"[A-Za-z0-9_\-:.]{1,64}\Z")


def new_state() -> dict:
    return {"items": {}, "clock": 0}


def generate_key(a: str | None, b: str | None) -> str:
    """A key strictly between a and b (None = open bound). Keys never end in 'a'."""
    a = a or ""
    if b is not None:
        n = 0
        while n < len(b) and (a[n] if n < len(a) else "a") == b[n]:
            n += 1
        if n:
            return b[:n] + generate_key(a[n:], b[n:])
    da = ord(a[0]) - 97 if a else 0
    db = ord(b[0]) - 97 if b else 26
    if db - da > 1:
        return chr(97 + (da + db + 1) // 2)
    if b and len(b) > 1:
        return b[:1]
    return chr(97 + da) + generate_key(a[1:], None)


def _stamp(op) -> tuple:
    return (op["lamport"], op["node"])


def valid_op(op) -> bool:
    if not isinstance(op, dict) or op.get("op") not in ("ins", "mov", "del"):
        return False
    if not (isinstance(op.get("id"), str) and _ID.match(op["id"]) and isinstance(op.get("node"), str) and _ID.match(op["node"])
            and isinstance(op.get("lamport"), int) and not isinstance(op["lamport"], bool) and 0 <= op["lamport"] < 2**53):
        return False
    if op["op"] != "del" and not (isinstance(op.get("key"), str) and _KEY.match(op["key"]) and not op["key"].endswith("a")):
        return False
    if op["op"] == "ins":
        r = op.get("ref")
        return isinstance(r, dict) and isinstance(r.get("content_ref"), str) and 0 < len(r["content_ref"]) <= 512
    return True


def _slot(state, i):
    return state["items"].setdefault(i, {"key": "", "ref": None, "by": "", "at": 0, "deleted": False, "ks": (-1, "")})


def apply(state: dict, op: dict) -> dict:
    if not valid_op(op):
        return state
    state["clock"] = max(state["clock"], op["lamport"])
    if op["id"] not in state["items"] and len(state["items"]) >= MAX_ITEMS:
        return state
    it = _slot(state, op["id"])
    if op["op"] == "del":
        it["deleted"] = True
        return state
    if op["op"] == "ins" and it["ref"] is None:
        r = op["ref"]
        it["ref"], it["by"], it["at"] = r["content_ref"], str(r.get("added_by", ""))[:60], r.get("added_at", 0)
    if _stamp(op) > tuple(it["ks"]):
        it["key"], it["ks"] = op["key"], _stamp(op)
    return state


def merge(a: dict, b: dict) -> dict:
    out = new_state()
    out["clock"] = max(a["clock"], b["clock"])
    for i in set(a["items"]) | set(b["items"]):
        x, y = a["items"].get(i), b["items"].get(i)
        if x is None or y is None:
            out["items"][i] = dict(x or y)
            continue
        hi = x if tuple(x["ks"]) >= tuple(y["ks"]) else y
        src = x if x["ref"] is not None else y
        out["items"][i] = {"key": hi["key"], "ks": tuple(hi["ks"]), "ref": src["ref"], "by": src["by"], "at": src["at"],
                           "deleted": x["deleted"] or y["deleted"]}
    return out


def ordered(state: dict) -> list[dict]:
    live = [(v["key"], i, v) for i, v in state["items"].items() if not v["deleted"] and v["ref"] is not None]
    return [{"id": i, "key": k, "content_ref": v["ref"], "added_by": v["by"], "added_at": v["at"]} for k, i, v in sorted(live, key=lambda t: (t[0], t[1]))]


def rebalance_ops(state: dict, node: str, lamport: int) -> list[dict]:
    """Deterministic: re-key live items evenly with 3-letter keys (tied to current order)."""
    live = ordered(state)
    n = len(live)
    step = 26 ** 3 // (n + 1)
    ops = []
    for idx, it in enumerate(live, 1):
        v, key = idx * step, ""
        for _ in range(3):
            v, d = divmod(v, 26)
            key = chr(97 + d) + key
        key = key.rstrip("a") or "b"
        ops.append({"op": "mov", "id": it["id"], "key": key, "lamport": lamport, "node": node})
    return ops


class Replica:
    def __init__(self, node: str) -> None:
        self.node, self.state, self.log = node, new_state(), []

    def _emit(self, op: dict) -> dict:
        apply(self.state, op)
        self.log.append(op)
        return op

    def _tick(self) -> int:
        self.state["clock"] += 1
        return self.state["clock"]

    def _key_between(self, after: str | None, before: str | None) -> str:
        k = {i["id"]: i["key"] for i in ordered(self.state)}
        return generate_key(k.get(after), k.get(before))

    def insert(self, item_id: str, ref: dict, after: str | None = None, before: str | None = None) -> list[dict]:
        key = self._key_between(after, before)
        ops = [self._emit({"op": "ins", "id": item_id, "key": key, "ref": ref, "lamport": self._tick(), "node": self.node})]
        return ops + self._maybe_rebalance(key)

    def move(self, item_id: str, after: str | None = None, before: str | None = None) -> list[dict]:
        key = self._key_between(after, before)
        ops = [self._emit({"op": "mov", "id": item_id, "key": key, "lamport": self._tick(), "node": self.node})]
        return ops + self._maybe_rebalance(key)

    def delete(self, item_id: str) -> list[dict]:
        return [self._emit({"op": "del", "id": item_id, "lamport": self._tick(), "node": self.node})]

    def _maybe_rebalance(self, key: str) -> list[dict]:
        if len(key) <= MAX_KEY:
            return []
        lam = self._tick()
        return [self._emit(o) for o in rebalance_ops(self.state, self.node, lam)]

    def receive(self, ops) -> None:
        for op in ops:
            apply(self.state, op)
            if op in self.log:
                continue
            if valid_op(op):
                self.log.append(op)
