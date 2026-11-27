"""Opt-in, token-protected local HTTP control API (issue #269).

Lets automation (Home Assistant, scripts) pause, resume, stop, seek, query and
cast without the GUI. It is a separate headless process, so it never starts
unless you run it::

    smoothcast --control-api token                       # print (and create) the token
    smoothcast --control-api serve [--bind ADDR] [--port N] [--media-root DIR ...]

Security model
* Disabled by default: nothing listens until ``serve`` is run explicitly.
* Every request needs ``Authorization: Bearer <token>`` (constant-time check).
  The token lives in an owner-only file (0600) or ``SMOOTHCAST_CONTROL_TOKEN``.
* Binds to loopback by default; ``--bind`` accepts only loopback or a private
  LAN IPv4 address, never ``0.0.0.0`` or a public address.
* No CORS headers are sent, so web pages cannot call it from a browser.
* ``POST /v1/cast`` is refused unless ``--media-root`` directories are given,
  and only files inside them (after resolving ``..`` and symlinks) can be cast.
* Bodies are small JSON objects; every field is validated here, then the same
  handlers as the command line (``cli_control``) do the work, one at a time.

Endpoints (all JSON; ``device`` is a receiver name or IPv4)::

    GET  /v1/health                         -> {"ok": true, "version": "..."}
    GET  /v1/status?device=NAME             -> receiver state, position, volume, session
    POST /v1/pause   {"device": NAME}
    POST /v1/resume  {"device": NAME}
    POST /v1/stop    {"device": NAME}
    POST /v1/seek    {"device": NAME, "time": "1:02:03"}        (or seconds)
    POST /v1/cast    {"device": NAME, "file": "/media/a.mkv", "mode": "auto",
                      "offset": "0:30", "subs": PATH, "no_subs": false,
                      "quality": "balanced", "audio": "original", "title": "..."}

Success: ``{"ok": true, "command": ..., ...}``. Failure: ``{"ok": false,
"command": ..., "error": ..., "message": ...}`` with HTTP 400 (bad request),
401/403 (auth / cast not allowed), 404, 405, 413, 422 (media), 502 (receiver
refused) or 503 (receiver unreachable).
"""
from __future__ import annotations

import paths
import argparse
import hmac
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import cli_control
import command_trace
import version

TOKEN_ENV = "SMOOTHCAST_CONTROL_TOKEN"
DEFAULT_PORT = 8800
MIN_TOKEN_LENGTH = 16
MAX_BODY = 64 * 1024
REQUEST_TIMEOUT = 10.0
MAX_FIELD = 4096
_MODES = ("auto", "direct", "transcode")
_QUALITIES = ("high", "balanced", "saver")
_AUDIO = ("original", "dialogue", "night")
_HTTP_FOR_EXIT = {cli_control.EXIT_USAGE: 400, cli_control.EXIT_UNREACHABLE: 503,
                  cli_control.EXIT_MEDIA: 422, cli_control.EXIT_FAILED: 502}
_ERROR_NAMES = {400: "bad_request", 401: "unauthorized", 403: "forbidden",
                404: "not_found", 405: "method_not_allowed", 413: "too_large",
                422: "media", 502: "failed", 503: "unreachable", 500: "internal"}


class ControlApiError(ValueError):
    """Configuration problem (token, bind address, port, media root)."""


class RequestError(Exception):
    """A request that must be rejected with a specific HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


# --- configuration ---------------------------------------------------------

def default_token_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / paths.APP_DIR / "control_api_token"


def validate_bind(address: str) -> str:
    """Loopback or a private LAN IPv4 address only; never wildcard or public."""
    text = "127.0.0.1" if address.strip().lower() == "localhost" else address.strip()
    try:
        ip = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ControlApiError(f"--bind must be an IPv4 address, not {address!r}") from exc
    if ip.version != 4 or ip.is_unspecified or ip.is_multicast:
        raise ControlApiError(f"refusing to bind {address}: use 127.0.0.1 or a private LAN IPv4 address")
    if not (ip.is_loopback or ip.is_private):
        raise ControlApiError(f"refusing to bind public address {address}")
    return str(ip)


def validate_port(port: object) -> int:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ControlApiError("port must be an integer from 1024 to 65535")
    return port


def load_token(path: Path | None = None, *, create: bool = False) -> str:
    """The shared secret: ``SMOOTHCAST_CONTROL_TOKEN``, else the owner-only token file.

    With ``create`` a new random token is written atomically with mode 0600.
    A readable-by-others token file is refused on POSIX.
    """
    env = os.environ.get(TOKEN_ENV, "").strip()
    if env:
        if len(env) < MIN_TOKEN_LENGTH:
            raise ControlApiError(f"{TOKEN_ENV} must be at least {MIN_TOKEN_LENGTH} characters")
        return env
    token_path = path or default_token_path()
    if not token_path.exists():
        if not create:
            raise ControlApiError(f"no token: run 'smoothcast --control-api token' (expected {token_path})")
        token_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(32) + "\n")
    if os.name == "posix" and token_path.stat().st_mode & 0o077:
        raise ControlApiError(f"{token_path} must not be readable by others (chmod 600)")
    token = token_path.read_text().strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise ControlApiError(f"token in {token_path} is too short; delete it and run 'token' again")
    return token


def resolve_media_roots(roots: list[str]) -> list[Path]:
    resolved = []
    for root in roots:
        path = Path(root).expanduser().resolve()
        if not path.is_dir():
            raise ControlApiError(f"--media-root is not a directory: {root}")
        resolved.append(path)
    return resolved


# --- request validation ----------------------------------------------------

def _text(body: dict, key: str, *, required: bool = False, max_len: int = MAX_FIELD) -> str:
    value = body.get(key)
    if value is not None and not isinstance(value, str):
        raise RequestError(400, f"invalid field: {key}")
    text = (value or "").strip()
    if not text:
        if required:
            raise RequestError(400, f"missing field: {key}")
        return ""
    if len(text) > max_len or "\x00" in text:
        raise RequestError(400, f"invalid field: {key}")
    return text


def _device(body: dict) -> str:
    device = _text(body, "device", required=True, max_len=200)
    if device.startswith("-"):
        raise RequestError(400, "invalid field: device")
    return device


def _choice(body: dict, key: str, allowed: tuple[str, ...], default: str) -> str:
    value = body.get(key, default)
    if value not in allowed:
        raise RequestError(400, f"{key} must be one of: {', '.join(allowed)}")
    return str(value)


def _check_media(path_text: str, roots: list[Path], *, what: str) -> Path:
    if not roots:
        raise RequestError(403, "casting is disabled: start the server with --media-root DIR")
    try:
        path = Path(path_text).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RequestError(422, f"no such {what}") from exc
    if not path.is_file() or not any(path.is_relative_to(root) for root in roots):
        raise RequestError(403, f"{what} is outside the allowed media roots")
    return path


def build_args(command: str, body: dict, roots: list[Path]) -> argparse.Namespace:
    """Validated ``cli_control`` arguments for *command* from a JSON body."""
    args: dict[str, Any] = {"command": command, "device": _device(body), "json": True}
    if command == "seek":
        value = body.get("time")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise RequestError(400, "time must be seconds or [H:]MM:SS")
        args["time"] = str(value)
    elif command == "cast":
        args["file"] = str(_check_media(_text(body, "file", required=True), roots, what="file"))
        subs = _text(body, "subs")
        args["subs"] = str(_check_media(subs, roots, what="subtitle file")) if subs else None
        args["no_subs"] = bool(body.get("no_subs", False))
        args["mode"] = _choice(body, "mode", _MODES, "auto")
        args["quality"] = _choice(body, "quality", _QUALITIES, "balanced")
        args["audio"] = _choice(body, "audio", _AUDIO, "original")
        args["offset"] = _text(body, "offset", max_len=32) or None
        args["title"] = _text(body, "title", max_len=200) or None
    return argparse.Namespace(**args)


# --- HTTP server -----------------------------------------------------------

class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], token: str, roots: list[Path]) -> None:
        super().__init__(address, _Handler)
        self.token = token
        self.roots = roots
        self.command_lock = threading.Lock()  # one receiver command at a time


class _Handler(BaseHTTPRequestHandler):
    server: ControlServer
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT
    server_version = "SmoothCastControl"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"control-api {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    # -- plumbing ----------------------------------------------------------
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 401:
            self.send_header("WWW-Authenticate", 'Bearer realm="smoothcast"')
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _fail(self, command: str, status: int, message: str) -> None:
        self._send(status, {"ok": False, "command": command,
                            "error": _ERROR_NAMES.get(status, "failed"), "message": message})

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            supplied.strip().encode(), self.server.token.encode())

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise RequestError(400, "bad Content-Length") from exc
        if length < 0:
            raise RequestError(400, "bad Content-Length")
        if length > MAX_BODY:
            raise RequestError(413, f"body larger than {MAX_BODY} bytes")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RequestError(400, "body must be a JSON object") from exc
        if not isinstance(body, dict):
            raise RequestError(400, "body must be a JSON object")
        return body

    def _run(self, command: str, body: dict) -> None:
        try:
            args = build_args(command, body, self.server.roots)
            with self.server.command_lock:
                with command_trace.scope("control_api", command):
                    result = cli_control.HANDLERS[command](args)
        except RequestError as exc:
            self._fail(command, exc.status, exc.message)
        except cli_control.CliError as exc:
            self._fail(command, _HTTP_FOR_EXIT.get(exc.code, 502), exc.message)
        except Exception:  # never leak internals or crash the server thread
            self._fail(command, 500, "internal error")
        else:
            self._send(200, {"ok": True, "command": command, **result})

    # -- verbs -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parts = _split(self.path)
        if not self._authorised():
            return self._fail("auth", 401, "missing or invalid bearer token")
        if parts.path == "/v1/health":
            return self._send(200, {"ok": True, "command": "health", "version": version.label()})
        if parts.path == "/v1/status":
            device = (parse_qs(parts.query).get("device") or [""])[0]
            return self._run("status", {"device": device})
        self._fail(parts.path, 405 if parts.path.startswith("/v1/") else 404,
                   "not found" if not parts.path.startswith("/v1/") else "use POST for this endpoint")

    def do_POST(self) -> None:  # noqa: N802
        path = _split(self.path).path
        if not self._authorised():
            return self._fail("auth", 401, "missing or invalid bearer token")
        command = path.removeprefix("/v1/")
        if not path.startswith("/v1/") or command not in {"pause", "resume", "stop", "seek", "cast"}:
            return self._fail(path, 405 if command in {"status", "health"} else 404, "not found")
        try:
            body = self._body()
        except RequestError as exc:
            return self._fail(command, exc.status, exc.message)
        self._run(command, body)

    def _not_allowed(self) -> None:
        self._fail("method", 405, "method not allowed")

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _not_allowed  # noqa: N815


def _split(target: str):
    """urlsplit that never raises: an unparsable target is just an unknown path."""
    try:
        return urlsplit(target)
    except ValueError:
        return urlsplit("/invalid")


def make_server(bind: str, port: int, token: str, roots: list[Path]) -> ControlServer:
    return ControlServer((validate_bind(bind), validate_port(port)), token, roots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smoothcast --control-api", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("token", help="create the token file if needed and print the token")
    serve = sub.add_parser("serve", help="run the control API until interrupted")
    serve.add_argument("--bind", default="127.0.0.1", help="loopback or private LAN IPv4 (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--media-root", action="append", default=[], metavar="DIR",
                       help="directory casts may read from (repeatable); without it /v1/cast is refused")
    serve.add_argument("--token-file", type=Path, default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.action == "token":
            print(load_token(create=True))
            return 0
        token = load_token(args.token_file, create=False)
        server = make_server(args.bind, args.port, token, resolve_media_roots(args.media_root))
    except (ControlApiError, OSError) as exc:
        print(f"smoothcast --control-api: {exc}", file=sys.stderr)
        return 2
    host, port = str(server.server_address[0]), server.server_address[1]
    print(f"control API listening on http://{host}:{port} (casting "
          f"{'allowed under ' + ', '.join(map(str, server.roots)) if server.roots else 'disabled'})",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
