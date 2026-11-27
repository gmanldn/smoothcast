"""Carry fenced acquisition messages over the authenticated mesh RPC (#589).

``mesh_acquisition_rpc`` defines the messages, ``HostCoordinator`` (room host,
sole queue authority) and ``WorkerService``. This bridge only transports them
on the protected ``acquisition_job`` RPC kind, with the same trust model as
the read-only telemetry: current membership identity, boot id and *numeric
source address* must match, and both peers must negotiate
``mesh.acquisition.assign.v1`` (a separate capability, never overloaded onto
the v1 telemetry token or the node digest). A worker also needs the operator's
explicit opt-in (``accept``). This is trusted-LAN authentication, not
cryptography. No URL, infohash, path or peer address is ever put in a message.

``send`` is synchronous for ``HostCoordinator`` and MUST NOT be called on the
mesh loop thread; ``call_soon`` schedules the actual RPC onto the loop.
"""
from __future__ import annotations

from collections.abc import Callable
import json
import re
import threading

import link_acquisition as links

import mesh_acquisition_rpc as wire
import mesh_membership as membership
import peer_protocol as protocol

HINT = "acquisition-assign-v1"
CAPABILITY = "mesh.acquisition.assign.v1"
SEARCH_CAPABILITY = "mesh.acquisition.search.v1"
SEARCH_HINT = "acquire-youtube-search-v1"
_SEARCH_TYPES = frozenset({"search_start", "search_poll", "search_cancel"})
_SEARCH_ID = re.compile(r"[0-9a-f]{32}\Z")
_SEARCH_TTL = links.SEARCH_SECONDS + 15
RPC_KIND = "acquisition_job"
TIMEOUT = 3.0
_WORKER_TYPES = frozenset({"offer", "cancel", "ticket"})
_HOST_TYPES = frozenset({"report", "finished", "failed"})


class AcquisitionBridge:
    def __init__(self, *, clock, rpc, members, record, own, version: str,
                 call_soon: Callable[[Callable[[], None]], None],
                 on_loop: Callable[[], bool] = lambda: False,
                 disabled=lambda _node: frozenset(),
                 accept: Callable[[], bool] = lambda: False,
                 worker: wire.WorkerService | None = None,
                 host: wire.HostCoordinator | None = None) -> None:
        self.clock, self.rpc, self.members, self.record, self.own = clock, rpc, members, record, own
        self.call_soon, self.on_loop, self.disabled, self.accept = call_soon, on_loop, disabled, accept
        self.worker, self.host = worker, host
        self.hello = protocol.local_handshake(version, caps=(CAPABILITY, SEARCH_CAPABILITY))
        self.search_provider = None
        self._search_job = None
        self._closed = False
        rpc.register(RPC_KIND, self._answer, protected=True)

    def close(self) -> None:
        self._closed = True
        if self._search_job is not None:
            self._search_job["cancel"].set()

    # -- shared trust checks -------------------------------------------------
    def _agrees(self, hello, node, capability=CAPABILITY) -> bool:
        try:
            remote = protocol.parse_handshake(hello)
            return protocol.negotiate(
                self.hello, remote, disabled=self.disabled(node)).supports(capability)
        except protocol.PeerCompatibilityError:
            return False

    def _envelope(self, reply: dict) -> dict:
        own = self.own()
        return {"hello": self.hello.wire(), "node": own.node_id, "boot": own.boot_id, "reply": reply}

    # -- receiving side ------------------------------------------------------
    def _answer(self, source, body):
        if self._closed or not isinstance(body, dict):
            return None
        own = self.own()
        if body.get("target") != own.node_id or body.get("target_boot") != own.boot_id:
            return None
        peer = next((m for m in self.members() if m.node_id == body.get("node")
                     and m.boot_id == body.get("boot") and m.address == source
                     and m.status == membership.ALIVE), None)
        if peer is None or not self._agrees(body.get("hello"), peer.node_id):
            return None
        message = body.get("msg")
        kind = message.get("t") if isinstance(message, dict) else None
        if kind in _SEARCH_TYPES:
            if not self._agrees(body.get("hello"), peer.node_id, SEARCH_CAPABILITY):
                return None
            return self._envelope(self._search_answer(peer, message))
        if kind in _WORKER_TYPES and self.worker is not None:
            if not self.accept():
                return self._envelope({"ok": False, "verdict": "declined"})
            return self._envelope(self.worker.handle(message, sender=peer.node_id))
        if kind in _HOST_TYPES and self.host is not None:
            applied = self.host.on_message(peer.node_id, message, self.clock.monotonic())
            return self._envelope({"ok": bool(applied), "verdict": "applied" if applied else "refused"})
        return None

    def _search_answer(self, peer, message: dict) -> dict:
        """One bounded background search; never block the mesh event loop."""
        kind, request = message.get("t"), message.get("id")
        keys = {"t", "id", "q"} if kind == "search_start" else {"t", "id"}
        if set(message) != keys or not isinstance(request, str) or not _SEARCH_ID.fullmatch(request):
            return {"ok": False, "verdict": "invalid"}
        owner = (peer.node_id, peer.boot_id, request)
        job = self._search_job
        if job is not None and self.clock.monotonic() >= job["expires"]:
            job["cancel"].set()
        if job is not None and job["cancel"].is_set() and job["done"].is_set():
            self._search_job = job = None
        if not self.accept():
            if job is not None:
                job["cancel"].set()
            return {"ok": False, "verdict": "declined"}
        if job is not None and job["owner"] == owner:
            if kind == "search_cancel":
                job["cancel"].set()
                return {"ok": True, "verdict": "cancelled"}
            if not job["done"].is_set():
                return {"ok": True, "verdict": "pending"}
            if kind == "search_poll":
                self._search_job = None
            return job["reply"]
        if kind != "search_start":
            return {"ok": False, "verdict": "unknown"}
        if job is not None:
            return {"ok": False, "verdict": "busy"}
        provider = self.search_provider
        if (provider is None or not provider.capabilities().get("youtube")
                or not callable(getattr(provider, "search_youtube", None))):
            return {"ok": False, "verdict": "unavailable"}
        try:
            query = links._search_text(message["q"])
        except links.LinkError:
            return {"ok": False, "verdict": "invalid"}
        job = {"owner": owner, "expires": self.clock.monotonic() + _SEARCH_TTL,
               "cancel": threading.Event(), "done": threading.Event(),
               "reply": {"ok": False, "verdict": "failed"}}
        self._search_job = job

        def run():
            try:
                results = provider.search_youtube(query, job["cancel"].is_set)
                raw = b"\n".join(json.dumps(row, allow_nan=False).encode("utf-8")
                                  for row in results[:links.SEARCH_LIMIT])
                if not job["cancel"].is_set():
                    job["reply"] = {"ok": True, "verdict": "ready",
                                    "results": links.youtube_results(raw)}
            except links.LinkError as exc:
                if exc.status == 429:
                    job["reply"] = {"ok": False, "verdict": "busy"}
            except (TypeError, ValueError, OSError):
                pass  # bounded failure; never expose worker internals
            finally:
                job["done"].set()

        try:
            threading.Thread(target=run, name="mesh-youtube-search", daemon=True).start()
        except RuntimeError:
            self._search_job = None
            return {"ok": False, "verdict": "unavailable"}
        return {"ok": True, "verdict": "pending"}

    # -- sending side (blocking; never on the loop thread) --------------------
    def send(self, node_id: str, message: dict) -> dict:
        """Deliver one message to *node_id*; raise ConnectionError if the outcome
        is unknown (the caller must then treat ownership as ambiguous)."""
        if self.on_loop():
            raise RuntimeError("acquisition send must not block the mesh loop")
        search = message.get("t") in _SEARCH_TYPES
        capability = SEARCH_CAPABILITY if search else CAPABILITY
        own = self.own()
        peer = next((m for m in self.members() if m.node_id == node_id
                     and m.status == membership.ALIVE), None)
        record = self.record(node_id)
        if (peer is None or record is None or HINT not in getattr(record, "capabilities", ())
                or record.boot_id != peer.boot_id or self.disabled(node_id) & {CAPABILITY, capability}
                or (search and SEARCH_HINT not in getattr(record, "capabilities", ()))):
            raise ConnectionError("peer is not available for acquisition")
        body = {"hello": self.hello.wire(), "node": own.node_id, "boot": own.boot_id,
                "target": peer.node_id, "target_boot": peer.boot_id, "msg": message}
        done = threading.Event()
        outcome: list = []

        def replied(value, error):
            outcome.append((value, error))
            done.set()

        self.call_soon(lambda: self.rpc.call(peer.endpoint, RPC_KIND, body, replied, timeout=TIMEOUT))
        if not done.wait(TIMEOUT + 1.0) or not outcome:
            raise ConnectionError("no answer from peer")
        value, error = outcome[0]
        current = next((m for m in self.members() if m.node_id == node_id
                        and m.status == membership.ALIVE), None)
        if (error or not isinstance(value, dict) or current is None
                or (current.boot_id, current.endpoint) != (peer.boot_id, peer.endpoint)
                or value.get("node") != peer.node_id or value.get("boot") != peer.boot_id
                or not self._agrees(value.get("hello"), peer.node_id, capability)
                or not isinstance(value.get("reply"), dict)):
            raise ConnectionError("unverified reply from peer")
        return value["reply"]
