"""Declarative portal route table (#689 first slice). Pure: no HTTP, no GTK.

Each ``Route`` names the method, an exact path or prefix, and the policy the handler
applies (auth, CSRF, throttle class). ``match`` is the single lookup so policy lives in
data instead of scattered ``if path == ...`` chains. Unwired until ``portal.py`` dispatches
through it; the table mirrors the current ``do_GET``/``do_POST`` order.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: str
    prefix: bool = False
    auth: bool = True
    csrf: bool = False
    throttle: str = ""


def _get(path, handler, **kw):
    return Route("GET", path, handler, **kw)


def _post(path, handler, **kw):
    return Route("POST", path, handler, csrf=kw.pop("csrf", True), **kw)


ROUTES: tuple[Route, ...] = (
    _get("/", "page", auth=False),
    _get("/index.html", "page", auth=False),
    _get("/nodes", "nodes_page", auth=False),
    _get("/api/openapi.json", "openapi", auth=False),
    _get("/silence.wav", "silence", auth=False),
    _get("/api/config", "config", auth=False),
    _get("/api/session", "session", throttle="read"),  # cookie-checked by its own handler
    _get("/api/libraries", "libraries", throttle="read"),
    _get("/api/libraries/", "libraries", prefix=True, throttle="read"),
    _get("/api/search/stream", "search_stream", throttle="read"),
    _get("/api/search", "search", throttle="read"),
    _get("/mesh/library/", "mesh_library", prefix=True),
    _get("/mesh/file/", "mesh_file", prefix=True),
    _get("/api/events", "events"),
    _get("/api/status", "status", throttle="read"),
    _post("/api/login", "login", auth=False, csrf=False),
    _post("/api/uploads/target", "upload_target", throttle="upload"),
    _post("/api/uploads/announce", "upload_announce", throttle="upload"),
    _post("/api/uploads", "upload", throttle="upload"),
    _post("/api/search/magnets", "search_magnets", throttle="mutation"),
    _post("/api/search/youtube", "search_youtube", throttle="mutation"),
    _post("/api/profile", "profile", throttle="mutation"),
    _get("/api/settings", "settings", throttle="read"),
    _post("/api/settings", "settings_update", throttle="mutation"),
    _post("/api/action", "action", throttle="mutation"),
)


def match(method: str, path: str, routes: tuple[Route, ...] = ROUTES) -> Route | None:
    """First route whose method and path fit; exact beats prefix regardless of order."""
    prefix_hit = None
    for r in routes:
        if r.method != method:
            continue
        if not r.prefix and r.path == path:
            return r
        if r.prefix and prefix_hit is None and path.startswith(r.path):
            prefix_hit = r
    return prefix_hit


def public_paths(routes: tuple[Route, ...] = ROUTES) -> set[str]:
    return {r.path for r in routes if not r.auth and not r.prefix}
