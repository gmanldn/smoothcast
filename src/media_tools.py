"""Where SmoothCast finds ffmpeg, ffprobe and ffplay (issue #530).

GTK-free. A source checkout and the Linux/macOS bundles keep the existing
behaviour: the bare tool name, found through PATH. The frozen **Windows**
application is stricter: it only ever runs the copies shipped next to it, at

    <folder holding SmoothCast.exe>/ffmpeg/<tool>.exe

and never falls back to PATH, the registry, MSYS2 or another install. A missing
or replaced sidecar is a clear, catalogued failure (``ffmpeg.bundled_missing``),
not a silent switch to whatever ffmpeg happens to be on the machine.

Callers build argv lists with ``resolve_media_tool``; they never use a shell.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import Literal

from async_jobs import UserFacingError
import frozen_runtime

MediaTool = Literal["ffmpeg", "ffprobe", "ffplay"]
TOOLS: tuple[str, ...] = ("ffmpeg", "ffprobe", "ffplay")
SIDECAR_DIR = "ffmpeg"
MISSING_CODE = "ffmpeg.bundled_missing"


class MediaToolMissing(UserFacingError, FileNotFoundError):
    """A bundled media tool is absent or untrusted.

    Also a ``FileNotFoundError`` so existing "tool not installed" handling at a
    call site keeps degrading the same way it does for a missing PATH tool.
    """

    default_code = MISSING_CODE

    def __init__(self, tool: str, detail: str = "") -> None:
        UserFacingError.__init__(
            self, f"SmoothCast's built-in {tool} is missing. Reinstall SmoothCast.",
            detail=detail or None, code=MISSING_CODE,
        )


def _strict() -> bool:
    """True only in a frozen Windows build, the one place PATH is never trusted."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def _install_root() -> Path:
    """The one layout contract: sidecars sit beside the frozen executables."""
    return frozen_runtime.install_root()


def _check_name(name: str) -> str:
    if name not in TOOLS:
        raise ValueError(f"unknown media tool: {name!r}")
    return name


def _bundled(name: str) -> Path:
    """Absolute, verified path of a shipped tool, or raise ``MediaToolMissing``."""
    root = _install_root().resolve()
    candidate = root / SIDECAR_DIR / f"{name}.exe"
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise MediaToolMissing(name, f"Expected {candidate.name} in the {SIDECAR_DIR} folder.") from None
    if resolved.parent != (root / SIDECAR_DIR).resolve() or not resolved.is_file():
        raise MediaToolMissing(name, "The file is not where SmoothCast installed it.")
    return resolved


def resolve_media_tool(name: MediaTool) -> str:
    """Return what to put at argv[0]: the bare name, or the trusted shipped path."""
    _check_name(name)
    return str(_bundled(name)) if _strict() else name


def find_media_tool(name: MediaTool) -> str | None:
    """Like ``shutil.which`` for a media tool; never searches PATH when strict."""
    _check_name(name)
    if not _strict():
        return shutil.which(name)
    try:
        return str(_bundled(name))
    except MediaToolMissing:
        return None


def probe() -> dict:
    """Headless report for support/CI: every tool resolved or missing. Runs nothing."""
    tools: dict[str, str | None] = {name: find_media_tool(name) for name in TOOLS}  # type: ignore[arg-type]
    return {"strict": _strict(), "tools": tools, "ok": all(tools.values())}


def report(*, run=subprocess.run) -> dict:
    """Headless payload check for ``SmoothCastCLI --_smoothcast-media-probe`` (#530).

    Runs only ``<tool> -version`` with a short timeout: no media, display or
    receiver. Paths are omitted so the output is safe in a support bundle.
    """
    import ffmpeg_compat
    tools: dict[str, dict] = {}
    for name in TOOLS:
        entry: dict = {"found": False, "version": "", "ok": False}
        tools[name] = entry
        try:
            path = find_media_tool(name)  # type: ignore[arg-type]
            if path is None:
                entry["problem"] = "missing"
                continue
            entry["found"] = True
            result = run([path, "-version"], stdin=subprocess.DEVNULL, capture_output=True,
                         text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            entry["problem"] = type(exc).__name__
            continue
        lines = (result.stdout or "").strip().splitlines()
        entry["version"] = lines[0].strip()[:120] if lines else ""
        entry["ok"] = result.returncode == 0 and bool(entry["version"])
        if name == "ffmpeg" and entry["ok"]:
            parsed = ffmpeg_compat.parse_version(entry["version"])
            entry["ok"] = parsed is not None and parsed >= ffmpeg_compat.MINIMUM
            if not entry["ok"]:
                entry["problem"] = "needs FFmpeg 5.0 or newer"
    return {"strict": _strict(), "tools": tools, "ok": all(e["ok"] for e in tools.values())}
