"""Browser routes for the live mesh view (ticket #402): ``/api/mesh`` snapshot,
``/api/mesh/events`` Server-Sent Events and ``/api/mesh/heartbeat`` for the
dedicated primary-node heartbeat. Same auth as the rest of the room: paired
session cookie, Host check, no CSRF (read-only). Returns 503 until a ``MeshFeed``
is attached to the portal server (the app does this when the mesh runs, #405).
"""
from __future__ import annotations

import json

import mesh_clients

KEEPALIVE_S = 15.0
STREAM_TIMEOUT_S = 60.0
MAX_STREAM_SECONDS = 8 * 3600


def route(handler, method: str, path: str) -> bool:
    if method != "GET" or path not in {"/api/mesh", "/api/mesh/events",
                                       "/api/mesh/heartbeat"}:
        return False
    if not handler._authenticated():
        handler._error(401, "Enter the PIN shown in SmoothCast")
        return True
    feed = getattr(handler.server, "mesh_feed", None)
    if feed is None:
        handler._error(503, "The mesh is not running")
        return True
    if path == "/api/mesh/heartbeat":
        handler._send(200, {"ok": True, "heartbeat": _heartbeat(handler.server)})
        return True
    if path == "/api/mesh":
        view = feed._publisher.view
        body = mesh_clients.guest_snapshot(view, feed._primary())
        beat = _heartbeat(handler.server)
        if beat is not None:
            body["heartbeat"] = beat
        handler._send(200, {"ok": True, "mesh": body,
                            "event": f"{feed.generation}:{feed.last_event}"})
        return True
    key = handler.server._session_key(handler._cookie_token() or "")
    try:
        stream = feed.open(key, handler.headers.get("Last-Event-ID"))
    except mesh_clients.FeedFull:
        handler._error(429, "Too many live mesh connections")
        return True
    _serve(handler, stream)
    return True


def _heartbeat(server) -> dict | None:
    """Latest dedicated-heartbeat reading attached by the app, or None."""
    provider = getattr(server, "mesh_heartbeat", None)
    if provider is None:
        return None
    try:
        beat = provider()
    except Exception:
        return None
    return beat if isinstance(beat, dict) else None


def _serve(handler, stream) -> None:
    handler.connection.settimeout(STREAM_TIMEOUT_S)
    handler.close_connection = True
    handler.send_response(200)
    for name, value in (("Content-Type", "text/event-stream; charset=utf-8"),
                        ("Cache-Control", "no-store"), ("X-Accel-Buffering", "no"),
                        ("X-Content-Type-Options", "nosniff"), ("Connection", "close")):
        handler.send_header(name, value)
    handler.end_headers()
    waited = 0.0
    try:
        while not stream.closed and waited < MAX_STREAM_SECONDS:
            frames = stream.poll()
            if frames:
                handler.wfile.write(b"".join(frames))
                handler.wfile.flush()
            elif not stream.wait(KEEPALIVE_S):
                if stream.closed:
                    break
                handler.wfile.write(mesh_clients.KEEPALIVE)
                handler.wfile.flush()
                waited += KEEPALIVE_S
            # A revoked or expired session must not keep a stream open.
            if not handler.server.session_key_active(stream.key):
                break
    except (OSError, ValueError):
        pass
    finally:
        stream.close()


def encode_event(data: dict) -> bytes:        # helper for tests and diagnostics
    return json.dumps(data, separators=(",", ":")).encode()
