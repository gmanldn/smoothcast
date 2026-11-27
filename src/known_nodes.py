"""Known-node identity pinning for automatic mesh membership (#418). Pure + atomic JSON.

``known_nodes.json``: {version:1, nodes:{node_id:{fp, first_seen, name}}}. First fingerprint per node id is
pinned (TOFU). A different fingerprint later -> ``identity_changed``: the peer is treated as a NEW node id
(``quarantine_id``) and nothing is merged until a person accepts. The auto-join kill switch restores today's
manual pairing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

VERSION = 1
SETTING = "Join other SmoothCast computers automatically"
MAX_NODES = 500
_ID = re.compile(r"[A-Za-z0-9:_\-.]{4,80}\Z")
_FP = re.compile(r"[0-9a-fA-F:]{16,128}\Z")


def conflict_message(name: str) -> str:
    return f"{name} was reinstalled or replaced. Accept the new identity?"


class Known:
    def __init__(self, path: Path | None = None, clock=None) -> None:
        import time
        self.path, self.clock = (Path(path) if path else None), clock or time.time
        self.nodes: dict[str, dict] = {}
        self.conflicts: dict[str, dict] = {}              # node_id -> {fps:{fp:name}, since}
        if self.path:
            try:
                d = json.loads(self.path.read_text("utf-8"))
                if d.get("version") == VERSION and isinstance(d.get("nodes"), dict):
                    self.nodes = {k: v for k, v in d["nodes"].items() if isinstance(v, dict) and "fp" in v}
            except (OSError, ValueError, AttributeError):
                pass

    def observe(self, node_id: str, fp: str, name: str = "", compatible: bool = True, auto_join: bool = True) -> dict:
        """-> {action: join|pending|identity_changed|reject, node_id (effective id), message?}."""
        if not (isinstance(node_id, str) and _ID.match(node_id) and isinstance(fp, str) and _FP.match(fp)):
            return {"action": "reject", "node_id": node_id, "message": ""}
        fp = fp.lower()
        known = self.nodes.get(node_id)
        if known and known["fp"] != fp:
            c = self.conflicts.setdefault(node_id, {"fps": {}, "since": self.clock()})
            c["fps"][fp] = (name or node_id)[:60]
            return {"action": "identity_changed", "node_id": self.quarantine_id(node_id, fp), "message": conflict_message(known.get("name") or name or node_id)}
        if not compatible:
            return {"action": "reject", "node_id": node_id, "message": ""}
        if not auto_join:
            return {"action": "pending", "node_id": node_id, "message": ""}      # today's manual pairing
        if known is None:
            if len(self.nodes) >= MAX_NODES:
                return {"action": "reject", "node_id": node_id, "message": ""}
            self.nodes[node_id] = {"fp": fp, "first_seen": self.clock(), "name": (name or node_id)[:60]}
            self._save()
        return {"action": "join", "node_id": node_id, "message": ""}

    @staticmethod
    def quarantine_id(node_id: str, fp: str) -> str:
        """Distinct id so the changed peer never merges into the pinned node's data."""
        return f"{node_id}~{hashlib.sha256(fp.encode()).hexdigest()[:8]}"

    def accept(self, node_id: str, fp: str) -> bool:
        c = self.conflicts.get(node_id)
        if not c or fp.lower() not in c["fps"]:
            return False
        self.nodes[node_id] = {"fp": fp.lower(), "first_seen": self.clock(), "name": c["fps"][fp.lower()]}
        del self.conflicts[node_id]
        self._save()
        return True

    def health_rows(self) -> list[dict]:
        """Rows for the house-health view (#386)."""
        return [{"node": n, "status": "amber", "reasons": [conflict_message((self.nodes.get(n) or {}).get("name") or n)],
                 "identities": len(c["fps"]) + 1} for n, c in sorted(self.conflicts.items())]

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".kn")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": VERSION, "nodes": self.nodes}, fh)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
