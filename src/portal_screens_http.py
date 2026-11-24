"""HTTP routes for room screens, kept out of ``portal`` to keep that file small.

``route`` is called by the portal handler for every request. It returns ``True``
when it handled (and answered) the request. All state-changing routes need the
paired session cookie *and* the CSRF token, exactly like the rest of the room;
media and poll reads need the cookie only.
"""
from __future__ import annotations

from collections import OrderedDict
import guest_messages
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit

import portal_join
import portal_media
import portal_screen_page
import portal_screens

_SCREEN_ROUTE = re.compile(r"^/api/screens/([a-f0-9]{8})(?:/(poll|report|command))?$")
_MEDIA_ROUTE = re.compile(r"^/api/media/([A-Za-z0-9_-]{1,64})$")
_PATH_TTL = 3.0
_PATH_CAPACITY = 64
_STREAM_TIMEOUT = 60.0


class _PathCache:
    """Tiny TTL cache so a ranged <video> does not hop to GTK for every chunk."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, dict]] = OrderedDict()

    def get(self, item: str) -> dict | None:
        with self._lock:
            entry = self._items.get(item)
            if entry is None or entry[0] <= self._clock():
                self._items.pop(item, None)
                return None
            return entry[1]

    def put(self, item: str, value: dict) -> None:
        with self._lock:
            self._items[item] = (self._clock() + _PATH_TTL, value)
            self._items.move_to_end(item)
            while len(self._items) > _PATH_CAPACITY:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def attach(server) -> None:
    """Give a portal server its screen registry and media-path cache."""
    server.screens = portal_screens.ScreenRegistry(
        clock=server.clock, can_transcode=portal_media.can_transcode)
    server.media_paths = _PathCache(clock=server.clock)


def route(handler, method: str, path: str) -> bool:
    if path == "/join-qr.png" and method == "GET":
        # Only the server's bound IPv4 endpoint, never a user-controlled Host or PIN.
        ip, port = handler.server.server_address[:2]
        try:
            png = portal_join.qr_png(f"http://{ip}:{port}/")
        except (ValueError, ImportError):
            handler._error(503, "Room join QR unavailable on this network")
        else:
            handler._send(200, png, content_type="image/png")
        return True
    if path == "/join-slate.png" and method == "GET":
        # Same numeric endpoint rule as the QR; the TV idle slate must never carry a PIN.
        ip, port = handler.server.server_address[:2]
        try:
            png = portal_join.render_join_slate(f"http://{ip}:{port}/", "SmoothCast")
        except (ValueError, ImportError):
            handler._error(503, "Room join slate unavailable on this network")
        else:
            handler._send(200, png, content_type="image/png")
        return True
    if path == "/screen" and method == "GET":
        handler._send(200, portal_screen_page.screen_page(),
                      content_type="text/html; charset=utf-8")
        return True
    if path == "/api/screens" and method in {"GET", "POST"}:
        _guarded(handler, lambda: _list(handler) if method == "GET"
                 else _register(handler), csrf=method == "POST")
        return True
    match = _SCREEN_ROUTE.fullmatch(path)
    if match is not None:
        screen_id, verb = match.groups()
        if verb == "poll" and method == "GET":
            _guarded(handler, lambda: _poll(handler, screen_id))
        elif verb == "report" and method == "POST":
            _guarded(handler, lambda: _report(handler, screen_id), csrf=True)
        elif verb == "command" and method == "POST":
            _guarded(handler, lambda: _command(handler, screen_id), csrf=True)
        elif verb is None and method == "DELETE":
            _guarded(handler, lambda: _remove(handler, screen_id), csrf=True)
        else:
            handler._error(405, "Method not allowed")
        return True
    match = _MEDIA_ROUTE.fullmatch(path)
    if match is not None and method in {"GET", "HEAD"}:
        _guarded(handler, lambda: _media(handler, match.group(1), method == "HEAD"))
        return True
    return False


def _guarded(handler, action, *, csrf: bool = False) -> None:
    if not handler._authenticated(csrf=csrf):
        status = 403 if csrf else 401
        message = (guest_messages.SESSION_ENDED if csrf
                   else "Enter the PIN shown in SmoothCast")
        return handler._error(status, message)
    try:
        action()
    except portal_screens.ScreenError as exc:
        handler._error(exc.status, exc.message)
    except portal_media.MediaError as exc:
        handler._error(exc.status, exc.message)
    except Exception as exc:
        # portal.PortalRequestError (raised by the GTK owner) carries a safe
        # status and message; anything else is an internal failure.
        code = getattr(exc, "status", None)
        text = getattr(exc, "message", None)
        if isinstance(code, int) and isinstance(text, str):
            return handler._error(code, text)
        handler._error(503, "SmoothCast could not complete that request")


def _key(handler) -> str:
    return handler.server._session_key(handler._cookie_token() or "")


def _participant(handler) -> str:
    return handler.server.session_participant(handler._cookie_token()) or ""


def _list(handler) -> None:
    handler._send(200, {"ok": True, "screens": handler.server.screens.snapshot()})


def _register(handler) -> None:
    body = handler._body()
    screen = handler.server.screens.register(
        _key(handler), _participant(handler), body.get("name"),
        body.get("capabilities"), claim=body.get("claim"))
    handler._send(200, {"ok": True, "screen": {
        "id": screen.id, "name": screen.name, "seq": screen.seq,
        "play_seq": screen.play_seq}})


def _query(handler) -> dict[str, list[str]]:
    try:
        return parse_qs(urlsplit(handler.path).query, max_num_fields=8)
    except ValueError:
        return {}


def _int_arg(handler, name: str, default: int, upper: int) -> int:
    values = _query(handler).get(name)
    try:
        return max(0, min(int(values[0]), upper)) if values else default
    except ValueError:
        return default


def _poll(handler, screen_id: str) -> None:
    since = _int_arg(handler, "since", 0, 2**31)
    wait = _int_arg(handler, "wait", 0, int(portal_screens.POLL_WAIT_MAX))
    result = handler.server.screens.poll(screen_id, _key(handler), since, float(wait))
    handler._send(200, {"ok": True, **result, **_queue_hint(handler)})


def _queue_hint(handler) -> dict:
    """``queue_empty`` from the cached status snapshot; never blocks on the GTK thread.

    Omitted when unknown so the screen keeps its default layout (#420).
    """
    snapshot = handler.server.status_snapshot
    try:
        state = snapshot() if snapshot is not None else None
    except Exception:
        return {}
    queue = state.get("queue") if isinstance(state, dict) else None
    return {"queue_empty": not queue} if isinstance(queue, list) else {}


def _report(handler, screen_id: str) -> None:
    body = handler._body()
    result = handler.server.screens.report(screen_id, _key(handler), body)
    item = result["advance"]
    if item:
        _advance(handler, screen_id, item)
    handler._send(200, {"ok": True, "play_seq": result["play_seq"]})


def _queue_rows(handler) -> list[dict]:
    state = handler.server.dispatch("status", {})
    rows = state.get("queue") if isinstance(state, dict) else None
    return [row for row in rows if isinstance(row, dict)
            and isinstance(row.get("id"), str)] if isinstance(rows, list) else []


def _resolve(handler, item: str) -> dict:
    """Ask the GTK owner for a queue item's path; validate it before use."""
    cached = handler.server.media_paths.get(item)
    if cached is not None:
        return cached
    info = handler.server.dispatch("media_path", {
        "id": item, "_portal_auth_key": _key(handler)})
    if (not isinstance(info, dict) or not isinstance(info.get("path"), str)
            or not info["path"]):
        raise portal_media.MediaError(404, "That item is no longer in the queue")
    handler.server.media_paths.put(item, info)
    return info


def _advance(handler, screen_id: str, finished: str) -> None:
    """A following screen finished an item: start the next one in the queue."""
    try:
        rows = _queue_rows(handler)
    except Exception:
        return
    ids = [row["id"] for row in rows]
    if finished not in ids:
        return
    for row in rows[ids.index(finished) + 1:ids.index(finished) + 6]:
        try:
            _play(handler, screen_id, row["id"], follow=True, rows=rows)
            return
        except (portal_screens.ScreenError, portal_media.MediaError):
            continue          # skip an unplayable entry rather than stall
        except Exception:
            return


def _play(handler, screen_id: str, item: str, *, follow: bool, start: float = 0.0,
          command_id: object = None, rows: list[dict] | None = None) -> dict:
    info = _resolve(handler, item)
    row = next((r for r in (rows if rows is not None else _queue_rows(handler))
                if r.get("id") == item), {})
    title = info.get("title") or row.get("title") or "Untitled"
    duration = row.get("duration") or info.get("duration") or 0.0
    return handler.server.screens.command(
        screen_id, "play", command_id=command_id, item=item, title=title,
        duration=duration if isinstance(duration, (int, float)) else 0.0,
        suffix=portal_media.safe_suffix(info["path"]), follow=follow, start=start)


def _command(handler, screen_id: str) -> None:
    body = handler._body()
    action = body.get("action")
    command_id = body.get("command_id")
    if action == "play":
        item = body.get("item")
        if not isinstance(item, str):
            raise portal_screens.ScreenError(400, "Choose something from the queue")
        receipt = _play(handler, screen_id, item, follow=bool(body.get("follow")),
                        start=body.get("start") or 0.0, command_id=command_id)
    else:
        receipt = handler.server.screens.command(
            screen_id, action if isinstance(action, str) else "",
            command_id=command_id, value=body.get("value"))
    handler.server.room.record(_participant(handler), "screen",
                               {"action": action, "screen": screen_id})
    handler._send(202, receipt)


def _remove(handler, screen_id: str) -> None:
    if not handler.server.screens.remove(screen_id, _key(handler)):
        raise portal_screens.ScreenError(404, "That screen is no longer registered")
    handler._send(200, {"ok": True})


def _media(handler, item: str, head: bool) -> None:
    info = _resolve(handler, item)
    path = info["path"]
    suffix = portal_media.safe_suffix(path)
    query = _query(handler)
    mode = (query.get("mode") or [""])[0]
    start = 0.0
    try:
        start = float((query.get("start") or ["0"])[0])
    except ValueError:
        raise portal_media.MediaError(400, "Start position is invalid") from None
    if not 0 <= start <= portal_media.MAX_START_SECONDS:
        raise portal_media.MediaError(400, "Start position is out of range")
    kind = portal_screens.media_kind(suffix)
    if kind is None:
        raise portal_media.MediaError(415, "That file type cannot be played on a screen")

    def write_headers(status: int, headers: dict) -> None:
        handler.send_response(status)
        for name, value in headers.items():
            handler.send_header(name, value)
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
        handler.send_header("Content-Disposition", "inline")
        handler.send_header("Connection", "close")
        handler.end_headers()

    # A paused or buffering browser stops reading; allow it to idle without the
    # short request timeout used for ordinary API calls.
    handler.connection.settimeout(_STREAM_TIMEOUT)
    handler.close_connection = True
    with portal_media.stream_slot():
        if mode == "transcode":
            mime = "video/mp4" if kind == "video" else "audio/mp4"
            portal_media.serve_transcode(handler, path, kind, start, mime,
                                         write_headers=write_headers, head=head)
            return
        mime = portal_screens.direct_mime(suffix)
        if not mime:
            raise portal_media.MediaError(
                415, "This format needs the host to convert it for your screen")
        portal_media.serve_direct(handler, path, mime, head=head,
                                  write_headers=write_headers)
