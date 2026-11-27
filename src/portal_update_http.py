"""Browser routes for the one-click update (#711): ``GET/POST /api/update``.

Only the host's own browser (loopback) may start an update unless the app sets
``server.update_allow_remote``; everyone with a paired session may read the
status. 503 until the app attaches an ``UpdateRunner`` as ``server.update_runner``.
"""
from __future__ import annotations

import threading

PATHS = {"/api/update"}


def _is_host(handler) -> bool:
    if getattr(handler.server, "update_allow_remote", False):
        return True
    return handler.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def route(handler, method: str, path: str) -> bool:
    if path not in PATHS or method not in ("GET", "POST"):
        return False
    if not handler._authenticated(csrf=method == "POST"):
        handler._error(401, "Enter the PIN shown in SmoothCast")
        return True
    runner = getattr(handler.server, "update_runner", None)
    if runner is None:
        handler._error(503, "Updates are not available on this install")
        return True
    host = _is_host(handler)
    if method == "GET":
        handler._send(200, {"ok": True, "can_start": host, **runner.snapshot()})
        return True
    if not host:
        handler._error(403, "Only the computer running SmoothCast can update it")
        return True
    body = handler._body()
    if body.get("action") == "check":
        threading.Thread(target=runner.check, daemon=True, name="update-check").start()
        handler._send(202, {"ok": True, **runner.snapshot()})
        return True
    result = runner.apply(confirmed=body.get("confirmed") is True)
    handler._send(200 if result.get("ok") or result.get("needs_confirmation") else 409, result)
    return True
