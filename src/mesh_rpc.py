"""Tiny typed request/response router over a ``mesh_ports.Transport`` (ticket #397).

Several mesh layers (membership probes, record sync) share one request channel.
``RpcRouter`` owns the transport's request handler and dispatches by *kind*:
payload ``<kind>\\n<json>``, reply ``<json>``. Everything is size bounded; an
unknown kind, malformed body or raising handler yields no reply (the caller sees
"refused"), never an exception on the mesh loop. GTK-free.
"""
from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any

from mesh_ports import Transport

MAX_RPC_BYTES = 128 * 1024
_KIND = re.compile(r"^[a-z][a-z0-9_]{0,23}$")

Handler = Callable[[str, dict[str, Any]], "dict[str, Any] | None"]
Callback = Callable[["dict[str, Any] | None", "str | None"], None]


def encode_request(kind: str, body: dict[str, Any]) -> bytes:
    if not _KIND.fullmatch(kind):
        raise ValueError("invalid rpc kind")
    data = kind.encode("ascii") + b"\n" + json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > MAX_RPC_BYTES:
        raise ValueError("rpc request is too large")
    return data


class RpcRouter:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
        self._handlers: dict[str, Handler] = {}
        self.errors = 0
        transport.set_request_handler(self._dispatch)

    def register(self, kind: str, handler: Handler) -> None:
        if not _KIND.fullmatch(kind):
            raise ValueError("invalid rpc kind")
        self._handlers[kind] = handler

    def call(self, address: str, kind: str, body: dict[str, Any], callback: Callback,
             timeout: float = 3.0) -> None:
        """Send a request; *callback* gets ``(reply, None)`` or ``(None, error)`` once."""
        try:
            payload = encode_request(kind, body)
        except (ValueError, TypeError):
            callback(None, "invalid")
            return

        def done(reply: bytes | None, error: str | None) -> None:
            if reply is None:
                callback(None, error or "failed")
                return
            try:
                value = json.loads(reply.decode("utf-8")) if len(reply) <= MAX_RPC_BYTES else None
            except (ValueError, UnicodeError, RecursionError):
                value = None
            if isinstance(value, dict):
                callback(value, None)
            else:
                callback(None, "protocol")

        self._transport.request(address, payload, done, timeout)

    def _dispatch(self, source: str, payload: bytes) -> bytes | None:
        try:
            if len(payload) > MAX_RPC_BYTES:
                return None
            head, _, tail = payload.partition(b"\n")
            kind = head.decode("ascii")
            handler = self._handlers.get(kind)
            if handler is None:
                return None
            body = json.loads(tail.decode("utf-8")) if tail else {}
            if not isinstance(body, dict):
                return None
            reply = handler(source, body)
            if reply is None:
                return None
            return json.dumps(reply, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode("utf-8")
        except Exception:                       # never raise into the transport
            self.errors += 1
            return None
