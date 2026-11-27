"""OpenAPI 3.1 description of the room HTTP API (issue #434).

Hand-written and framework-free. ``tests/test_openapi_contract.py`` fails when a
route is added to the portal without being described here (and vice versa).
Served at ``GET /api/openapi.json`` and mirrored in ``docs/api/openapi.json``.
"""
from __future__ import annotations

import json

API_VERSION = "1.2"  # bumped only when the HTTP contract changes

JSON = "application/json"
ERR = {"description": "Error", "content": {JSON: {"schema": {"$ref": "#/components/schemas/Error"}}}}


def _op(summary: str, *, auth: bool = True, method_body: str | None = None,
        params: list[dict] | None = None, ok: str = "Success", content: str = JSON,
        csrf: bool = False, tag: str = "room") -> dict:
    op: dict = {"summary": summary, "tags": [tag],
                "responses": {"200": {"description": ok, "content": {content: {}}}, "4XX": ERR}}
    if params:
        op["parameters"] = params
    if method_body:
        op["requestBody"] = {"required": True, "content": {JSON: {"schema": {
            "$ref": f"#/components/schemas/{method_body}"}}}}
    security: list[dict] = []
    if auth:
        security = [{"session": []}] + ([{"csrf": []}] if csrf else [])
    op["security"] = security or [{}]
    return op


def _p(name: str, where: str = "query", required: bool = False, desc: str = "") -> dict:
    return {"name": name, "in": where, "required": required or where == "path",
            "description": desc, "schema": {"type": "string"}}


PATHS: dict[str, dict] = {
    "/": {"get": _op("The web remote (HTML)", auth=False, content="text/html")},
    "/api/config": {"get": _op("Pre-login room settings (pin_required, name)", auth=False)},
    "/api/login": {"post": _op("Join the room; returns a session cookie and CSRF token",
                               auth=False, method_body="Login")},
    "/api/session": {"get": _op("Resume an existing session after a reload")},
    "/api/profile": {"post": _op("Rename yourself in the room", csrf=True, method_body="Profile")},
    "/api/status": {"get": _op("Playback, queue, room presence, receiver state and link acquisitions")},
    "/api/link-jobs": {"post": _op("Acquire an authorised YouTube video or magnet into Up Next",
                                   csrf=True, method_body="LinkStart", tag="acquisition")},
    "/api/link-jobs/cancel": {"post": _op("Cancel your pending or downloading acquisition",
                                          csrf=True, method_body="LinkCancel", tag="acquisition")},
    "/api/link-jobs/retry": {"post": _op("Retry a failed or cancelled acquisition you own",
                                         csrf=True, method_body="LinkRetry", tag="acquisition")},
    "/api/action": {"post": _op(
        "Transport and queue commands (play_pause, stop, seek, volume, next, previous, "
        "queue_play, queue_remove, queue_move, queue_next, queue_clear, queue_vote, "
        "queue_add_key)", csrf=True, method_body="Action")},
    "/api/search": {"get": _op("Search every shared library in the house", params=[
        _p("q", required=True, desc="Query; filters kind: year: artist: album:"),
        _p("limit"), _p("cursor")], tag="search")},
    "/api/search/youtube": {"post": {
        **_op("Explicit metadata-only YouTube search through an enabled isolated worker",
              csrf=True, method_body="YouTubeSearch", tag="search"),
        "security": [{"session": [], "csrf": []}]}},
    "/api/search/magnets": {"post": {
        **_op("Explicit metadata-only archive (magnet) search through the room's link service",
              csrf=True, method_body="MagnetSearch", tag="search"),
        "security": [{"session": [], "csrf": []}]}},
    "/api/search/stream": {"get": _op(
        "Same search as server-sent events: results, more, done", params=[_p("q", required=True)],
        content="text/event-stream", tag="search")},
    "/api/events": {"get": _op(
        "Room state as server-sent events: one `state` event now and one per change (the playhead "
        "is not pushed; clients project it). `GET /api/status` remains the polling fallback.",
        content="text/event-stream", tag="room")},
    "/api/libraries": {"get": _op("Computers and their shared library folders", tag="search")},
    "/api/libraries/{origin}/{folder}": {"get": _op(
        "One level of a shared folder: sub-folders and files (relative paths only)",
        params=[_p("origin", "path"), _p("folder", "path"), _p("path"), _p("cursor")], tag="search")},
    "/api/mesh": {"get": _op("Snapshot of the live mesh (nodes, targets, clients)", tag="mesh")},
    "/api/mesh/events": {"get": _op("Live mesh updates (server-sent events)",
                                    content="text/event-stream", tag="mesh")},
    "/api/mesh/heartbeat": {"get": _op(
        "Dedicated primary-node heartbeat (coordinator, activities and counters)",
        tag="mesh")},
    "/api/uploads": {"post": _op("Start a resumable upload", csrf=True, method_body="UploadStart",
                                 tag="uploads")},
    "/api/uploads/{id}": {
        "put": _op("Send one chunk (Content-Range)", params=[_p("id", "path")], csrf=True, tag="uploads"),
        "delete": _op("Cancel an upload", params=[_p("id", "path")], csrf=True, tag="uploads")},
    "/api/uploads/{id}/complete": {"post": _op(
        "Finish an upload and queue it", params=[_p("id", "path")], csrf=True, tag="uploads")},
    "/api/screens": {"get": _op("List browser screens", tag="screens"),
                     "post": _op("Register this browser as a screen or speaker", csrf=True,
                                 tag="screens")},
    "/api/screens/{id}": {"get": _op("Screen state", params=[_p("id", "path")], tag="screens"),
                          "delete": _op("Remove a screen", params=[_p("id", "path")], csrf=True,
                                        tag="screens")},
    "/api/screens/{id}/poll": {"get": _op("Long-poll the next screen command",
                                          params=[_p("id", "path")], tag="screens")},
    "/api/screens/{id}/report": {"post": _op("Report screen playback progress",
                                             params=[_p("id", "path")], csrf=True, tag="screens")},
    "/api/screens/{id}/command": {"post": _op("Command a screen", params=[_p("id", "path")],
                                              csrf=True, tag="screens")},
    "/api/media/{id}": {"get": _op("Ranged media bytes for a screen (HEAD supported)",
                                   params=[_p("id", "path")], content="application/octet-stream",
                                   tag="screens")},
    "/screen": {"get": _op("The screen page (HTML)", auth=False, content="text/html", tag="screens")},
    "/nodes": {"get": _op("Fallback list of SmoothCast computers (HTML)", auth=False,
                          content="text/html")},
    "/silence.wav": {"get": _op("One second of silence for lock-screen controls", auth=False,
                                content="audio/wav")},
    "/mesh/library/generation": {"get": _op("Library epoch, sequence, count, capabilities",
                                            auth=False, tag="mesh-library")},
    "/mesh/library/changes": {"get": _op("Ordered library changes since a sequence (410 when stale)",
                                         auth=False, params=[_p("epoch", required=True),
                                                             _p("since", required=True), _p("limit")],
                                         tag="mesh-library")},
    "/mesh/library/snapshot": {"get": _op("Paginated snapshot of the shared library", auth=False,
                                          params=[_p("cursor"), _p("limit")], tag="mesh-library")},
    "/mesh/library/search": {"get": _op("Search this node's shared library only", auth=False,
                                        params=[_p("q", required=True), _p("limit")],
                                        tag="mesh-library")},
    "/mesh/file/{key}": {"get": _op("Ranged bytes by content key (served or proxied; HEAD supported)",
                                    auth=False, params=[_p("key", "path")],
                                    content="application/octet-stream", tag="mesh-library")},
    "/api/openapi.json": {"get": _op("This document", auth=False)},
}

# Capability required to call each route, declared beside the route table so a
# test can fail any route that lacks one. ``None`` means the route is open to
# anyone who reaches the LAN listener (no session, no capability). State-changing
# routes additionally require the session cookie and CSRF token already declared
# in ``PATHS``; this is the authorization layer on top of authentication.
ROUTE_CAPABILITIES: dict[tuple[str, str], str | None] = {
    # Public: open to any peer on the trusted home LAN.
    ("/", "get"): None,
    ("/api/config", "get"): None,
    ("/api/login", "post"): None,
    ("/api/openapi.json", "get"): None,
    ("/silence.wav", "get"): None,
    ("/screen", "get"): None,
    ("/nodes", "get"): None,
    # Mesh library reads are public and read-only.
    ("/mesh/library/generation", "get"): None,
    ("/mesh/library/changes", "get"): None,
    ("/mesh/library/snapshot", "get"): None,
    ("/mesh/library/search", "get"): None,
    ("/mesh/file/{key}", "get"): None,
    # Authenticated read: a paired session cookie.
    ("/api/session", "get"): "room:read",
    ("/api/status", "get"): "room:read",
    ("/api/search", "get"): "room:read",
    ("/api/search/stream", "get"): "room:read",
    ("/api/events", "get"): "room:read",
    ("/api/libraries", "get"): "room:read",
    ("/api/libraries/{origin}/{folder}", "get"): "room:read",
    ("/api/mesh", "get"): "mesh:read",
    ("/api/mesh/events", "get"): "mesh:read",
    ("/api/mesh/heartbeat", "get"): "mesh:read",
    ("/api/screens", "get"): "room:read",
    ("/api/screens/{id}", "get"): "room:read",
    ("/api/screens/{id}/poll", "get"): "room:read",
    ("/api/media/{id}", "get"): "media:read",
    # State-changing: cookie plus CSRF token.
    ("/api/profile", "post"): "room:write",
    ("/api/action", "post"): "room:write",
    ("/api/screens", "post"): "room:write",
    ("/api/screens/{id}", "delete"): "room:write",
    ("/api/screens/{id}/report", "post"): "room:write",
    ("/api/screens/{id}/command", "post"): "room:write",
    # Uploads.
    ("/api/uploads", "post"): "uploads:create",
    ("/api/uploads/{id}", "put"): "uploads:manage",
    ("/api/uploads/{id}", "delete"): "uploads:manage",
    ("/api/uploads/{id}/complete", "post"): "uploads:manage",
    # Link acquisition.
    ("/api/link-jobs", "post"): "link:acquire",
    ("/api/link-jobs/cancel", "post"): "link:acquire",
    ("/api/link-jobs/retry", "post"): "link:acquire",
    ("/api/search/youtube", "post"): "link:search",
    ("/api/search/magnets", "post"): "link:search",
}


def required_capability(path: str, method: str) -> str | None:
    """The capability a caller must hold to invoke ``method`` on ``path``.

    ``None`` means the route is open to anyone who reaches the LAN listener
    (no session, no capability). State-changing routes additionally require the
    session cookie and CSRF token already declared in ``PATHS``.
    """
    return ROUTE_CAPABILITIES.get((path, method))


SCHEMAS = {
    "Error": {"type": "object", "properties": {"ok": {"const": False}, "error": {"type": "string"}}},
    "Login": {"type": "object", "properties": {
        "name": {"type": "string", "maxLength": 40}, "pin": {"type": "string", "pattern": "^[0-9]{6}$"}}},
    "Profile": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
    "Action": {"type": "object", "required": ["action"], "properties": {
        "action": {"type": "string"}, "value": {}, "id": {"type": "string"},
        "key": {"type": "string", "pattern": "^qh:[0-9a-f]{32}$"},
        "queue_revision": {"type": "integer"}, "queue_command_id": {"type": "string"}}},
    "YouTubeSearch": {"type": "object", "required": ["q"], "properties": {
        "q": {"type": "string", "minLength": 1, "maxLength": 200}}},
    "MagnetSearch": {"type": "object", "required": ["q"], "properties": {
        "q": {"type": "string", "minLength": 1, "maxLength": 200}}},
    "LinkStart": {"type": "object", "required": ["url", "request_id", "authorised"], "properties": {
        "url": {"type": "string", "maxLength": 1500},
        "request_id": {"type": "string", "maxLength": 80},
        "authorised": {"const": True}}},
    "LinkCancel": {"type": "object", "required": ["id"], "properties": {
        "id": {"type": "string"}}},
    "LinkRetry": {"type": "object", "required": ["id"], "properties": {
        "id": {"type": "string"}}},
    "UploadStart": {"type": "object", "required": ["name", "size"], "properties": {
        "name": {"type": "string"}, "size": {"type": "integer"}, "queue": {"type": "boolean"}}},
}


def spec() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "SmoothCast room API", "version": API_VERSION,
                 "description": "HTTP/SSE API of a SmoothCast node on the trusted home LAN. "
                                "Sessions are cookie-based; mutations also need the CSRF token "
                                "returned by /api/login in X-CSRF-Token."},
        "servers": [{"url": "http://smoothcast.local"}],
        "paths": PATHS,
        "components": {
            "schemas": SCHEMAS,
            "securitySchemes": {
                "session": {"type": "apiKey", "in": "cookie", "name": "sc_portal_session"},
                "csrf": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token"}}},
    }


def dumps() -> str:
    return json.dumps(spec(), indent=2, sort_keys=True) + "\n"
