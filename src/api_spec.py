"""OpenAPI 3.1 description of the room HTTP API (issue #434).

Hand-written and framework-free. ``tests/test_openapi_contract.py`` fails when a
route is added to the portal without being described here (and vice versa).
Served at ``GET /api/openapi.json`` and mirrored in ``docs/api/openapi.json``.
"""
from __future__ import annotations

import json

API_VERSION = "1.0"  # bumped only when the HTTP contract changes

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
    "/api/status": {"get": _op("Playback, queue, room presence and receiver state")},
    "/api/action": {"post": _op(
        "Transport and queue commands (play_pause, stop, seek, volume, next, previous, "
        "queue_play, queue_remove, queue_move, queue_next, queue_clear, queue_vote, "
        "queue_add_key)", csrf=True, method_body="Action")},
    "/api/search": {"get": _op("Search every shared library in the house", params=[
        _p("q", required=True, desc="Query; filters kind: year: artist: album:"),
        _p("limit"), _p("cursor")], tag="search")},
    "/api/search/stream": {"get": _op(
        "Same search as server-sent events: results, more, done", params=[_p("q", required=True)],
        content="text/event-stream", tag="search")},
    "/api/mesh": {"get": _op("Snapshot of the live mesh (nodes, targets, clients)", tag="mesh")},
    "/api/mesh/events": {"get": _op("Live mesh updates (server-sent events)",
                                    content="text/event-stream", tag="mesh")},
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

SCHEMAS = {
    "Error": {"type": "object", "properties": {"ok": {"const": False}, "error": {"type": "string"}}},
    "Login": {"type": "object", "properties": {
        "name": {"type": "string", "maxLength": 40}, "pin": {"type": "string", "pattern": "^[0-9]{6}$"}}},
    "Profile": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
    "Action": {"type": "object", "required": ["action"], "properties": {
        "action": {"type": "string"}, "value": {}, "id": {"type": "string"},
        "key": {"type": "string", "pattern": "^qh:[0-9a-f]{32}$"},
        "queue_revision": {"type": "integer"}, "queue_command_id": {"type": "string"}}},
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
