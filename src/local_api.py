"""Versioned local API envelope and command validation for a headless core (#213). Pure.

Defines request/response framing, protocol-version negotiation and a closed set
of commands with argument validation. Transport (socket, auth) is not decided here.
"""
from __future__ import annotations

import math

API_VERSION = 1
MIN_SUPPORTED = 1
MAX_MESSAGE_BYTES = 64 * 1024

# command -> {argument: type}; all arguments are required.
COMMANDS: dict[str, dict[str, type]] = {
    "status": {},
    "play": {"media": str},
    "pause": {},
    "resume": {},
    "stop": {},
    "seek": {"position": float},
    "volume": {"level": float},
    "queue.add": {"media": str},
}
ERRORS = {"bad_request": 400, "unsupported_version": 426, "unknown_command": 404, "bad_arguments": 422}


def error(code: str, message: str, request_id=None) -> dict:
    return {"v": API_VERSION, "id": request_id, "ok": False,
            "error": {"code": code, "status": ERRORS.get(code, 400), "message": message}}


def ok(result, request_id=None) -> dict:
    return {"v": API_VERSION, "id": request_id, "ok": True, "result": result}


def _coerce(value, kind):
    if kind is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        return float(value)
    return value if isinstance(value, kind) and value and len(value) <= 4096 else None


def parse_request(msg) -> tuple[str, dict, object] | dict:
    """(command, validated args, request id) or an error response dict."""
    if not isinstance(msg, dict):
        return error("bad_request", "Request must be a JSON object.")
    rid = msg.get("id") if isinstance(msg.get("id"), (str, int)) else None
    version = msg.get("v")
    if isinstance(version, bool) or not isinstance(version, int) or not MIN_SUPPORTED <= version <= API_VERSION:
        return error("unsupported_version",
                     f"Supported API versions: {MIN_SUPPORTED}-{API_VERSION}.", rid)
    spec = COMMANDS.get(msg.get("cmd"))
    if spec is None:
        return error("unknown_command", "Unknown command.", rid)
    raw = msg.get("args") if isinstance(msg.get("args"), dict) else {}
    if set(raw) != set(spec):
        return error("bad_arguments", f"Expected arguments: {sorted(spec)}.", rid)
    args = {}
    for name, kind in spec.items():
        value = _coerce(raw[name], kind)
        if value is None:
            return error("bad_arguments", f"Invalid value for '{name}'.", rid)
        args[name] = value
    return msg["cmd"], args, rid
