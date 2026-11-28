"""Read-only acquisition observations across current LAN mesh members (#589).

Separate from v1 NodeRecord digests. A capability token is a discovery hint;
each RPC must negotiate its own feature handshake and match current membership
identity, boot and source address. This is trusted-LAN observation, not
cryptographic authentication or authority to assign/cancel remote jobs.
"""
from __future__ import annotations

from collections.abc import Callable
import re
import threading
from copy import deepcopy
from dataclasses import dataclass

import mesh_membership as membership
import mesh_model as model
import peer_protocol as protocol

HINT = "acquisition-telemetry-v1"
CAPABILITY = "mesh.acquisition.telemetry.v1"
RPC_KIND = "acquisition_status"
POLL_SECONDS = 1.0
REPEAT_SECONDS = 2.0
FRESH_SECONDS = 12.0
RETAIN_SECONDS = 40.0
MAX_INFLIGHT = 2
MAX_JOBS = 4
MAX_VISIBLE_JOBS = 32
MAX_BYTES = 2 * 1024**3
MAX_RATE = MAX_BYTES
ID = re.compile(r"[0-9a-f]{24}\Z")
ACTIVE = frozenset({"pending", "resolving", "downloading", "verifying", "queueing"})
KINDS = frozenset({"youtube", "magnet"})


def _integer(value, maximum):
    return value if type(value) is int and 0 <= value <= maximum else None


def clean_jobs(value, *, strict=False):
    """Allowlist wire fields. No titles, paths, URLs, infohashes or error text."""
    if not isinstance(value, (list, tuple)) or len(value) > (MAX_JOBS if strict else 24):
        raise ValueError("invalid acquisition rows")
    rows = []
    seen = set()
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid acquisition row")
        stage, kind, ident = row.get("stage"), row.get("kind"), row.get("id")
        if not isinstance(stage, str) or stage not in ACTIVE:
            if strict:
                raise ValueError("invalid acquisition stage")
            continue
        if (not isinstance(kind, str) or kind not in KINDS
                or not isinstance(ident, str) or not ID.fullmatch(ident) or ident in seen):
            raise ValueError("invalid acquisition identity")
        seen.add(ident)
        received = _integer(row.get("received"), MAX_BYTES)
        total = _integer(row.get("total"), MAX_BYTES)
        rate = _integer(row.get("rate"), MAX_RATE)
        if total == 0 or (received is not None and total is not None and received > total):
            total = None
        clean = {"id": ident, "kind": kind, "stage": stage, "received": received,
                 "total": total, "rate": rate}
        if row.get("remote") is True:  # executing for another room (#589)
            clean["remote"] = True
        rows.append(clean)
        if not strict and len(rows) >= MAX_JOBS:
            break
    return rows


@dataclass
class _Observation:
    boot: str
    endpoint: str
    rows: list[dict] | None = None
    observed: float = 0.0
    due: float = 0.0
    failed: bool = False
    inflight: bool = False


class AcquisitionActivity:
    """Loop-owned polling, thread-safe immutable-by-contract browser snapshots."""
    def __init__(self, *, clock, rpc, members, record, own, version: str,
                 local_jobs: Callable[[], list], disabled=lambda _node: frozenset()):
        self.clock = clock
        self.rpc = rpc
        self.members = members
        self.record = record
        self.own = own
        self.local_jobs = local_jobs
        self.disabled = disabled
        self.hello = protocol.local_handshake(version, caps=(CAPABILITY,))
        self._peers: dict[str, _Observation] = {}
        self._inflight = 0
        self._lock = threading.Lock()
        self._snapshot: dict = {"available": True, "nodes": [], "omitted_jobs": 0}
        self._revision = 0
        self._timer = None
        self._closed = False
        rpc.register(RPC_KIND, self._answer, protected=True)

    def _agrees(self, body, node):
        try:
            remote = protocol.parse_handshake(body.get("hello"))
            return protocol.negotiate(
                self.hello, remote, disabled=self.disabled(node)).supports(CAPABILITY)
        except protocol.PeerCompatibilityError:
            return False

    def _answer(self, source, body):
        if self._closed:
            return None
        own = self.own()
        if body.get("target") != own.node_id or body.get("target_boot") != own.boot_id:
            return None
        # Source is the numeric transport address, not a caller-supplied field.
        peer = next((m for m in self.members() if m.node_id == body.get("node")
                     and m.boot_id == body.get("boot") and m.address == source
                     and m.status == membership.ALIVE), None)
        if peer is None or not self._agrees(body, peer.node_id):
            return None
        try:
            rows = clean_jobs(self.local_jobs())
        except Exception:  # noqa: BLE001 - unavailable is reported as None
            return None  # unavailable is not an empty successful observation
        return {"hello": self.hello.wire(), "node": own.node_id,
                "boot": own.boot_id, "jobs": rows}

    def start(self):
        if not self._closed and self._timer is None:
            self._tick()

    def _eligible(self):
        out = {}
        for peer in self.members():
            record = self.record(peer.node_id)
            if (record is not None and record.boot_id == peer.boot_id
                    and HINT in record.capabilities
                    and CAPABILITY not in self.disabled(peer.node_id)):
                out[peer.node_id] = peer
        return out

    def _tick(self):
        if self._closed:
            return
        now = self.clock.monotonic()
        eligible = self._eligible()
        for node in tuple(self._peers):
            peer = eligible.get(node)
            saved = self._peers[node]
            if peer is None or (saved.boot, saved.endpoint) != (peer.boot_id, peer.endpoint):
                self._peers.pop(node)
        for node, peer in eligible.items():
            if node not in self._peers:
                self._peers[node] = _Observation(peer.boot_id, peer.endpoint)
        self._publish(eligible, now)
        # A departed/restarted peer can still have a transport request in
        # flight. Keep the global budget until its callback actually returns.
        free = MAX_INFLIGHT - self._inflight
        due = sorted((row.due, node) for node, row in self._peers.items()
                     if not row.inflight and row.due <= now
                     and eligible[node].status == membership.ALIVE)
        for _, node in due[:max(0, free)]:
            self._request(node, self._peers[node])
        self._timer = self.clock.call_later(POLL_SECONDS, self._tick)

    def _request(self, node, row):
        own = self.own()
        row.inflight = True
        self._inflight += 1
        body = {"hello": self.hello.wire(), "node": own.node_id, "boot": own.boot_id,
                "target": node, "target_boot": row.boot}

        def replied(value, _error):
            if not row.inflight:
                return
            row.inflight = False
            self._inflight -= 1
            if self._closed or self._peers.get(node) is not row:
                return
            eligible = self._eligible()
            peer = eligible.get(node)
            if (peer is None or (peer.boot_id, peer.endpoint) != (row.boot, row.endpoint)):
                return
            now = self.clock.monotonic()
            row.due = now + REPEAT_SECONDS
            try:
                if (peer.status != membership.ALIVE or not isinstance(value, dict)
                        or value.get("node") != node or value.get("boot") != row.boot
                        or not self._agrees(value, node)):
                    raise ValueError("unconfirmed acquisition observation")
                row.rows = clean_jobs(value.get("jobs"), strict=True)
                row.observed = now
                row.failed = False
            except (ValueError, TypeError):
                row.failed = True
                row.due = now + 5.0
            self._publish(eligible, now)

        try:
            self.rpc.call(row.endpoint, RPC_KIND, body, replied, timeout=2.0)
        except Exception:  # noqa: BLE001 - transport failure is reported through the reply callback
            replied(None, "transport")

    def _publish(self, eligible, now):
        nodes = []
        omitted = 0
        remaining = MAX_VISIBLE_JOBS
        for node, row in sorted(self._peers.items()):
            peer = eligible.get(node)
            record = self.record(node)
            if peer is None or record is None:
                continue
            age = now - row.observed
            if row.rows is None:
                freshness = "unavailable" if row.failed else "waiting"
                rows = []
            elif row.failed or peer.status != membership.ALIVE or age > FRESH_SECONDS:
                freshness = "stale"
                rows = row.rows if age <= RETAIN_SECONDS else []
            else:
                freshness = "live"
                rows = row.rows
            shown = rows[:remaining]
            remaining -= len(shown)
            omitted += len(rows) - len(shown)
            nodes.append({"node": node, "name": model.clean_text(record.name, model.MAX_NAME,
                                                                 fallback="SmoothCast"),
                          "freshness": freshness, "jobs": shown})
        snapshot = {"available": True, "nodes": nodes, "omitted_jobs": omitted}
        with self._lock:
            if snapshot != self._snapshot:
                self._snapshot = snapshot
                self._revision += 1

    def snapshot(self):
        with self._lock:
            return deepcopy(self._snapshot)

    def revision(self):
        with self._lock:
            return self._revision

    def close(self):
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()
        self._peers.clear()
        with self._lock:
            self._snapshot = {"available": False, "nodes": [], "omitted_jobs": 0}
            self._revision += 1
