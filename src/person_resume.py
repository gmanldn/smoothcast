"""Per-resident resume points with conflict-free merge across nodes (#365). Pure.

Records: {resident: {content_key: {pos, dur, updated_at, node_id, counter}}}.
Merge rule: higher (updated_at, node_id) wins; the per-node counter breaks
ties for the same node so a skewed clock can't regress a newer local write.
Guests never write. Max 500 per resident, least-recently-updated evicted.
"""
from __future__ import annotations

MAX_PER_RESIDENT = 500
NEAR_END = 0.95
MIN_POS = 10.0


def source_position(wall_elapsed: float, speed: float, start_pos: float) -> float:
    """Resume is stored in source time: wall seconds * speed since start_pos."""
    return max(0.0, start_pos + wall_elapsed * max(0.1, speed))


def _key(r: dict) -> tuple:
    return (r.get("updated_at", 0), r.get("node_id", ""), r.get("counter", 0))


class ResumeStore:
    def __init__(self, node_id: str, data: dict | None = None) -> None:
        self.node, self.records = node_id, (data or {})
        self._counter = max((r.get("counter", 0) for d in self.records.values() for r in d.values()
                             if r.get("node_id") == node_id), default=0)

    def record(self, resident: str | None, content_key: str, pos: float, dur: float, now: float) -> bool:
        if not resident or not content_key or dur <= 0:     # guests / unknown people never write
            return False
        rows = self.records.setdefault(resident, {})
        if pos < MIN_POS or pos >= dur * NEAR_END:
            rows.pop(content_key, None)                     # finished or barely started: no resume point
            return True
        self._counter += 1
        rows[content_key] = {"pos": round(pos, 1), "dur": dur, "updated_at": now, "node_id": self.node,
                             "counter": self._counter}
        self._evict(rows)
        return True

    def _evict(self, rows: dict) -> None:
        while len(rows) > MAX_PER_RESIDENT:
            del rows[min(rows, key=lambda k: _key(rows[k]))]

    def get(self, resident: str | None, content_key: str) -> dict | None:
        return (self.records.get(resident or "") or {}).get(content_key)

    def continue_row(self, resident: str, limit: int = 20) -> list[dict]:
        rows = self.records.get(resident, {})
        return [{"content_key": k, **v} for k, v in sorted(rows.items(), key=lambda kv: _key(kv[1]), reverse=True)][:limit]

    def delta(self, since: float = 0.0) -> list[dict]:
        return [{"resident": res, "content_key": k, **v} for res, rows in self.records.items()
                for k, v in rows.items() if v.get("updated_at", 0) > since]

    def apply(self, batch: list[dict]) -> int:
        """Idempotent merge of a peer's resume.delta; returns records that changed."""
        changed = 0
        for b in batch[:5000]:
            try:
                res, ck = str(b["resident"]), str(b["content_key"])
                rec = {"pos": float(b["pos"]), "dur": float(b["dur"]), "updated_at": float(b["updated_at"]),
                       "node_id": str(b["node_id"]), "counter": int(b.get("counter", 0))}
            except (KeyError, TypeError, ValueError):
                continue
            if rec["dur"] <= 0 or not 0 <= rec["pos"] <= rec["dur"]:
                continue
            rows = self.records.setdefault(res, {})
            cur = rows.get(ck)
            if cur is None or _key(rec) > _key(cur):
                rows[ck] = rec
                self._evict(rows)
                changed += 1
        return changed

    def forget_resident(self, resident: str) -> None:
        self.records.pop(resident, None)

    def prompt(self, resident: str | None, content_key: str) -> str | None:
        r = self.get(resident, content_key)
        if not r:
            return None
        s = int(r["pos"])
        return f"Resume from {s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"Resume from {s // 60}:{s % 60:02d}"
