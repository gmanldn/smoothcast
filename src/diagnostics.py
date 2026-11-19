"""Bounded, redacted diagnostic bundle export for SmoothCast bug reports.

Assembles a small JSON document with version, platform, tool and recent error
detail. The output never exposes the user's home directory, absolute media
paths, private/LAN IP addresses or credentials; it is written atomically with
owner-only permissions and a hard size ceiling. Standard library only and safe
to run without GTK, a display or a prepared virtual environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

MAX_BUNDLE_BYTES = 256 * 1024
MAX_ERROR_LINES = 200
MAX_ACTIVITY_LINES = 100
MAX_SERVER_LINES = 100
MAX_RECEIVER_FIELD = 120
MAX_STRING = 500
MAX_LOG_READ = 2 * 1024 * 1024

# IPv4 addresses (private or otherwise) are never useful in a report.
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
# Absolute path shapes are collapsed to their basename before export.
_WIN_PATH = re.compile(r"[A-Za-z]:\\[^\s\"']*")
_HOME_PATH = re.compile(r"~/[^\s\"']*")
_ABS_PATH = re.compile(r"(?<![\w~./])/(?:[^\s/\"']+/)+[^\s/\"']*")
_SENSITIVE_KEY = re.compile(r"(token|password|secret|credential|apikey|api_key)", re.I)


class DiagnosticError(ValueError):
    """The diagnostic bundle could not be assembled or written safely."""


def _basename(value: str) -> str:
    cleaned = value.replace("\\", "/").rstrip("/")
    name = cleaned.rsplit("/", 1)[-1]
    return name or "file"


def redact(text: object, *, home: str | None = None) -> str:
    """Mask private addresses and reduce absolute file paths to basenames.

    The home directory is replaced before path collapsing, so a path such as
    ``/home/alice/Movies/Film.mkv`` becomes ``Film.mkv`` while non-path prose
    is left intact. Long values are trimmed to keep bundles bounded.
    """
    value = str(text)
    if home:
        for form in {str(home), str(Path(str(home)).expanduser())}:
            if form:
                value = value.replace(form, "~")
    value = _IPV4.sub("[ip]", value)
    value = _WIN_PATH.sub(lambda match: _basename(match.group(0)), value)
    value = _HOME_PATH.sub(lambda match: _basename(match.group(0)), value)
    value = _ABS_PATH.sub(lambda match: _basename(match.group(0)), value)
    if len(value) > MAX_STRING:
        value = value[:MAX_STRING] + "…"
    return value


def tool_version(command: str, *args: str, timeout: float = 4.0) -> str:
    """Return the first line of a tool's version output, or '' if unavailable."""
    executable = shutil.which(command)
    if executable is None:
        return ""
    try:
        result = subprocess.run(
            [executable, *(args or ("-version",))],
            capture_output=True, text=True, timeout=timeout, errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (result.stdout or result.stderr or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _tail(source, limit: int) -> list[str]:
    """Return at most *limit* non-blank trailing lines from a path or iterable."""
    if source is None:
        return []
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                if size > MAX_LOG_READ:
                    handle.seek(size - MAX_LOG_READ)
                data = handle.read()
        except OSError:
            return []
        lines = data.decode("utf-8", "replace").splitlines()
    else:
        lines = [str(item) for item in source]
    return [line for line in lines if line.strip()][-limit:]


def redact_config(config: object, *, home: str | None = None) -> object:
    """Recursively redact credential keys and path/address values in settings."""
    if isinstance(config, dict):
        result = {}
        for key, value in config.items():
            name = str(key)
            if _SENSITIVE_KEY.search(name):
                result[name] = "[redacted]"
            else:
                result[name] = redact_config(value, home=home)
        return result
    if isinstance(config, (list, tuple)):
        return [redact_config(item, home=home) for item in config]
    if isinstance(config, str):
        return redact(config, home=home)
    return config


def receiver_report(dlna_renderer=None, cast_device=None) -> dict:
    """Comparable receiver facts for device-compatibility reports (#275).

    Duck-typed over the DLNA ``Renderer`` and Cast ``Device`` objects; keeps
    only protocol, model and maker. Network addresses and names are left out.
    """
    if dlna_renderer is not None:
        return {"protocol": "dlna", "model": str(getattr(dlna_renderer, "model", "") or "")}
    if cast_device is not None:
        return {"protocol": "cast", "model": str(getattr(cast_device, "model", "") or ""),
                "manufacturer": str(getattr(cast_device, "manufacturer", "") or "")}
    return {}


def _clean_receiver(receiver: object, home: str) -> dict:
    """Allow-list, bound and redact receiver fields from any caller."""
    if not isinstance(receiver, dict):
        return {}
    clean: dict = {}
    protocol = receiver.get("protocol")
    if protocol in ("cast", "dlna"):
        clean["protocol"] = protocol
    for key in ("model", "manufacturer"):
        value = receiver.get(key)
        if isinstance(value, str) and value.strip():
            clean[key] = redact(value.strip()[:MAX_RECEIVER_FIELD], home=home)
    return clean


def collect(*, error_log=None, activity=None, config=None, home=None, server_log=None,
            receiver=None) -> dict:
    """Assemble the redacted diagnostic document over known-safe inputs."""
    from version import __version__, label

    home_value = str(home) if home is not None else str(Path.home())
    payload: dict = {
        "smoothcast": {"version": __version__, "label": label()},
        "generated": int(time.time()),
        "python": platform.python_version(),
        "platform": redact(platform.platform(), home=home_value),
        "machine": platform.machine(),
        "tools": {},
        "errors": [redact(line, home=home_value)
                   for line in _tail(error_log, MAX_ERROR_LINES)],
        "activity": [redact(line, home=home_value)
                     for line in _tail(activity, MAX_ACTIVITY_LINES)],
        # HLS server errors (bad requests, bind failures, crashes), redacted.
        "server_log": [redact(line, home=home_value)
                       for line in _tail(server_log, MAX_SERVER_LINES)],
        "config": redact_config(config or {}, home=home_value),
        "receiver": _clean_receiver(receiver, home_value),
    }
    for name, args in (
        ("ffmpeg", ("-version",)), ("ffprobe", ("-version",)),
        ("ffplay", ("-version",)), ("catt", ("--version",)),
    ):
        version = tool_version(name, *args)
        payload["tools"][name] = redact(version, home=home_value) if version else "missing"
    return payload


def write_bundle(destination, payload: dict, *, max_bytes: int = MAX_BUNDLE_BYTES) -> Path:
    """Atomically write *payload* as owner-only JSON, refusing oversized output."""
    target = Path(destination)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8")
    if len(encoded) > max_bytes:
        raise DiagnosticError(f"Diagnostic bundle exceeds the {max_bytes}-byte limit")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb", prefix=".smoothcast-diag-", suffix=".tmp",
            dir=target.parent, delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise DiagnosticError(f"Could not write diagnostic bundle: {exc}") from exc
    return target


def default_error_log_path() -> Path:
    return Path.home() / ".config" / "cast-control" / "errors.log"


def default_server_log_path() -> Path:
    return Path.home() / ".cache" / "cast-control" / "server.log"


def default_path(*, directory=None, now: float | None = None) -> Path:
    base = Path(directory) if directory else Path.home() / ".config" / "cast-control"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    return base / f"diagnostics-{stamp}.json"


def export(*, destination=None, error_log=None, activity=None, config=None,
           home=None, server_log=None, receiver=None) -> Path:
    """Collect and write a bounded, redacted bundle; return the written path."""
    if error_log is None:
        error_log = default_error_log_path()
    if server_log is None:
        server_log = default_server_log_path()
    payload = collect(error_log=error_log, activity=activity, config=config, home=home,
                      server_log=server_log, receiver=receiver)
    return write_bundle(destination or default_path(), payload)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``smoothcast --diagnostics [PATH]`` (GTK-free)."""
    args = list(sys.argv[1:] if argv is None else argv)
    destination = Path(args[0]).expanduser() if args and not args[0].startswith("-") else None
    try:
        path = export(destination=destination)
    except DiagnosticError as exc:
        print(f"SmoothCast diagnostics: {exc}", file=sys.stderr)
        return 1
    print(f"SmoothCast diagnostic bundle written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
