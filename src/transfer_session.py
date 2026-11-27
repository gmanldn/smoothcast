"""Browser-to-mesh transfer session contract (#569). Pure state machine; clock, rng and storage are injected.

Endpoints modelled (docs/TRANSFER_ARCHITECTURE.md): POST /api/transfers, GET|HEAD /api/transfers/<id>,
PUT /api/transfers/<id>/data, POST /api/transfers/<id>/finalise, DELETE /api/transfers/<id>. Every method returns
``(http_status, json_body)``. Errors are ``{"error": code, "message": plain text}``; no path ever leaves.
"""
from __future__ import annotations

import re
import secrets

VERSION = 1
INTENTS = ("add", "play", "queue", "copy")
STATES = ("negotiating", "transferring", "buffering", "ready", "playing", "completed", "failed", "cancelled")
TERMINAL = {"completed", "failed", "cancelled"}
CHUNK = 8 * 1024 * 1024
MAX_FILE = 32 * 1024**3
MAX_PENDING_BYTES = 64 * 1024**3
MAX_PER_OWNER, MAX_ACTIVE = 4, 16
IDLE_TTL_S = 2 * 3600.0
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{1,64}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MIME = re.compile(r"[a-z0-9.+\-]+/[a-z0-9.+\-]+\Z")


def err(status: int, code: str, message: str, **extra) -> tuple[int, dict]:
    return status, {"error": code, "message": message, **extra}


def safe_name(name) -> str | None:
    if not isinstance(name, str):
        return None
    base = re.split(r"[\\/]", name)[-1].replace("\x00", "").strip().lstrip(".")
    base = "".join(c for c in base if ord(c) >= 32)[:200]
    return base or None


def guard(host: str | None, origin: str | None, on_lan: bool) -> tuple[int, dict] | None:
    """Host/Origin/CSRF + LAN-only. None = allowed."""
    if not on_lan:
        return err(403, "lan_only", "Transfers only work from inside the home network.")
    if origin and origin not in ("null",) and re.sub(r"^https?://", "", origin).rstrip("/") != (host or ""):
        return err(403, "cross_origin", "That request came from another website.")
    return None


class Transfers:
    def __init__(self, clock, rng=None) -> None:
        self.clock, self.rng = clock, rng or (lambda: secrets.token_hex(16))
        self.s: dict[str, dict] = {}
        self.ops: dict[tuple, str] = {}

    # ---- helpers
    def _pending_bytes(self) -> int:
        return sum(x["size"] - x["durable_bytes"] for x in self.s.values() if x["state"] not in TERMINAL)

    def _live(self, owner: str, tid: str):
        x = self.s.get(tid)
        if x is None or x["owner"] != owner:                     # other owners' sessions do not exist
            return None, err(404, "unknown_transfer", "That transfer doesn't exist.")
        if x["state"] not in TERMINAL and self.clock() >= x["expires_at"]:
            self._end(x, "failed", "expired")
        if x.get("error") == "expired":
            return None, err(410, "expired", "That transfer expired. Start it again.")
        return x, None

    def _end(self, x, state, error=None) -> None:
        x["state"], x["error"] = state, error

    def _touch(self, x) -> None:
        x["expires_at"] = self.clock() + IDLE_TTL_S

    def _view(self, x) -> dict:
        return {"version": VERSION, "id": x["id"], "state": x["state"], "intent": x["intent"], "name": x["name"], "size": x["size"], "received_bytes": x["received_bytes"],
                "durable_bytes": x["durable_bytes"], "route": x["route"], "target": x["target"], "upload": f"/api/transfers/{x['id']}/data", "chunk_size": CHUNK,
                "max_concurrency": 1, "expires_at": x["expires_at"], "capabilities": ["resume", "early_stream"] if x["early_stream"] else ["resume"], "error": x["error"]}

    @staticmethod
    def _pick(peers: list[dict], want: str | None = None, avoid: str | None = None) -> dict | None:
        ok = [p for p in peers if p.get("online") and p["id"] != avoid]
        if want:
            return next((p for p in ok if p["id"] == want), None)
        return min(ok, key=lambda p: (p.get("load", 0.0), p["id"]), default=None)

    # ---- API
    def create(self, owner: str, body, peers: list[dict]) -> tuple[int, dict]:
        if not isinstance(body, dict) or not isinstance(owner, str) or not owner:
            return err(400, "bad_request", "That request wasn't understood.")
        intent, op = body.get("intent"), body.get("client_op_id")
        name, size = safe_name(body.get("name")), body.get("size")
        mime, digest = body.get("media_type", "application/octet-stream"), body.get("digest")
        if intent not in INTENTS or not (isinstance(op, str) and _TOKEN.match(op)) or name is None:
            return err(400, "bad_request", "That request wasn't understood.")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            return err(400, "bad_size", "The file looks empty or its size is missing.")
        if size > MAX_FILE:
            return err(413, "too_large", "That file is larger than SmoothCast can take in one go.")
        if not (isinstance(mime, str) and _MIME.match(mime.lower())) or (digest is not None and not (isinstance(digest, str) and _SHA.match(digest))):
            return err(400, "bad_request", "That request wasn't understood.")
        fp = (intent, name, size, str(body.get("target")), digest)
        prior = self.ops.get((owner, op))
        if prior and prior in self.s:
            x = self.s[prior]
            return (200, self._view(x)) if x["fp"] == fp else err(409, "op_reused", "That request ID was already used for a different file.")
        target = body.get("target")
        want = target.get("node") if isinstance(target, dict) else None
        if intent == "copy" and not want:
            return err(400, "target_required", "Choose which computer should get the copy.")
        if want is not None and not any(p["id"] == want for p in peers):
            return err(404, "unknown_target", "That computer isn't part of this home.")
        node = self._pick(peers, want)
        if node is None:
            return err(409, "target_offline", "That computer is asleep or offline right now." if want else "No computer is available to take this right now.")
        act = [x for x in self.s.values() if x["state"] not in TERMINAL]
        if sum(1 for x in act if x["owner"] == owner) >= MAX_PER_OWNER or len(act) >= MAX_ACTIVE:
            return err(429, "too_many_transfers", "Too many transfers are running. Wait for one to finish.")
        if self._pending_bytes() + size > MAX_PENDING_BYTES:
            return err(507, "no_space", "There isn't enough room for that right now.")
        tid = self.rng()
        x = {"id": tid, "owner": owner, "intent": intent, "name": name, "size": size, "mime": mime.lower(), "digest": digest, "fp": fp, "state": "negotiating",
             "received_bytes": 0, "durable_bytes": 0, "route": "direct", "target": {"node": node["id"], "room": target.get("room") if isinstance(target, dict) else None},
             "early_stream": bool(body.get("early_stream")), "error": None, "expires_at": self.clock() + IDLE_TTL_S}
        self.s[tid] = x
        self.ops[(owner, op)] = tid
        return 201, self._view(x)

    def get(self, owner: str, tid: str) -> tuple[int, dict]:
        x, e = self._live(owner, tid)
        return e or (200, self._view(x))

    def put_chunk(self, owner: str, tid: str, offset, length) -> tuple[int, dict]:
        x, e = self._live(owner, tid)
        if e:
            return e
        if x["state"] in TERMINAL or x["state"] not in ("negotiating", "transferring"):
            return err(409, "not_accepting", "This transfer isn't accepting data any more.", state=x["state"])
        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (offset, length)) or length == 0:
            return err(400, "bad_range", "That chunk's position wasn't valid.")
        if length > CHUNK:
            return err(413, "chunk_too_large", "That chunk is bigger than agreed.", chunk_size=CHUNK)
        if offset != x["received_bytes"]:
            return err(409, "offset_mismatch", "Resume from where the server left off.", received_bytes=x["received_bytes"], durable_bytes=x["durable_bytes"])
        if offset + length > x["size"]:
            return err(416, "past_end", "That chunk goes past the end of the file.", size=x["size"])
        x["received_bytes"] += length
        x["state"] = "transferring"
        if x["received_bytes"] == x["size"]:
            x["state"] = "buffering"
        self._touch(x)
        return 200, self._view(x)

    def mark_durable(self, tid: str, n: int) -> None:
        x = self.s.get(tid)
        if x and x["state"] not in TERMINAL and isinstance(n, int) and not isinstance(n, bool):
            x["durable_bytes"] = max(x["durable_bytes"], min(n, x["received_bytes"]))

    def resume(self, owner: str, tid: str) -> tuple[int, dict]:
        """HEAD/status for resume: the client restarts at durable_bytes; unflushed bytes are discarded."""
        x, e = self._live(owner, tid)
        if e:
            return e
        if x["state"] in ("negotiating", "transferring", "buffering") and x["received_bytes"] != x["size"] or x["state"] == "transferring":
            x["received_bytes"] = x["durable_bytes"]
        return 200, self._view(x)

    def finalise(self, owner: str, tid: str, computed_digest: str | None = None) -> tuple[int, dict]:
        x, e = self._live(owner, tid)
        if e:
            return e
        if x["state"] in ("ready", "playing", "completed"):
            return 200, self._view(x)                           # idempotent: retry racing a finish
        if x["state"] != "buffering" or x["received_bytes"] != x["size"]:
            return err(409, "incomplete", "Not all of the file has arrived yet.", received_bytes=x["received_bytes"])
        if x["digest"] and computed_digest != x["digest"]:
            self._end(x, "failed", "digest_mismatch")
            return err(422, "digest_mismatch", "The file arrived damaged. Please send it again.")
        x["durable_bytes"] = x["size"]
        x["state"] = "ready"
        self._touch(x)
        return 200, self._view(x)

    def advance(self, tid: str, state: str) -> bool:
        """Mesh side: ready -> playing -> completed."""
        x = self.s.get(tid)
        order = {"ready": ("playing", "completed"), "playing": ("completed",)}
        if x and state in order.get(x["state"], ()):
            x["state"] = state
            return True
        return False

    def source_changed(self, owner: str, tid: str) -> tuple[int, dict]:
        x, e = self._live(owner, tid)
        if e:
            return e
        if x["state"] not in TERMINAL:
            self._end(x, "failed", "source_changed")
        return err(409, "source_changed", "The file changed on your device while it was sending. Please send it again.")

    def cancel(self, owner: str, tid: str) -> tuple[int, dict]:
        x, e = self._live(owner, tid)
        if e:
            return e
        if x["state"] == "cancelled":
            return 204, {}
        if x["state"] in ("completed", "failed"):
            return err(409, "already_finished", "That transfer already finished.", state=x["state"])
        self._end(x, "cancelled")
        return 204, {}

    def target_lost(self, node_id: str, peers: list[dict]) -> list[tuple[str, str]]:
        """A target went away: re-route without re-upload when bytes are durable (or nothing sent), else fail."""
        out = []
        for x in self.s.values():
            if x["state"] in TERMINAL or x["target"]["node"] != node_id:
                continue
            alt = self._pick(peers, avoid=node_id) if x["intent"] != "copy" else None
            if alt is not None and (x["durable_bytes"] > 0 or x["received_bytes"] == 0):
                x["target"]["node"], x["route"] = alt["id"], "relay" if x["durable_bytes"] else "direct"
                out.append((x["id"], f"rerouted:{alt['id']}"))
            else:
                self._end(x, "failed", "target_lost")
                out.append((x["id"], "failed"))
        return out
