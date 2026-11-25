"""Owner-facing availability of the isolated link workers (#588).

Pure and GTK-free: turns ``CommandProvider.readiness()`` plus what the running
room reports into one row per provider with a status (``ready``, ``off``,
``restart``, ``missing`` or ``failed``) and platform repair steps. Only reads
PATH/file facts already gathered by the provider; never runs a program,
contacts a source or claims the isolation launcher is secure.
"""
from __future__ import annotations

import sys

LABELS = {"youtube": "YouTube", "magnet": "BitTorrent magnets"}
ENGINE = {"youtube": "yt-dlp", "magnet": "aria2c"}
LAUNCHER = "owner-configured isolation launcher"
_INSTALL = {
    "linux": {"yt-dlp": "install yt-dlp with your package manager or 'pipx install yt-dlp'",
              "aria2c": "install aria2 with your package manager",
              "ffprobe": "install ffmpeg (it provides ffprobe) with your package manager"},
    "darwin": {"yt-dlp": "run 'brew install yt-dlp'", "aria2c": "run 'brew install aria2'",
               "ffprobe": "run 'brew install ffmpeg' (it provides ffprobe)"},
    "win32": {"yt-dlp": "run 'winget install yt-dlp.yt-dlp'",
              "aria2c": "run 'winget install aria2.aria2'",
              "ffprobe": "run 'winget install Gyan.FFmpeg' (it provides ffprobe)"},
}
_LAUNCHER_HELP = ("set SMOOTHCAST_LINK_SANDBOX to the absolute path of an executable launcher "
                  "that blocks local and private network access and limits files, disk, "
                  "processes and time; a reference Linux launcher ships as scripts/link_sandbox_bwrap.py "
                  "and 'smoothcast --link-check --qualify' attack-tests it before it is trusted")
_QUALIFY = "qualified isolation (run smoothcast --link-check --qualify)"
_QUALIFY_STEP = "run 'smoothcast --link-check --qualify' to attack-test the launcher before it is trusted"


def _platform(name: str | None) -> str:
    name = name or sys.platform
    return "win32" if name.startswith(("win", "cygwin")) else "darwin" if name == "darwin" else "linux"


def rows(readiness: dict, *, running: dict | None = None, platform: str | None = None) -> list[dict]:
    """One row per provider; ``running`` is the live room's ``LinkJobs.capabilities()``."""
    system = _platform(platform)
    out = []
    for kind in ("youtube", "magnet"):
        info = readiness.get(kind, {})
        missing = list(info.get("missing", ()))
        enabled = bool(info.get("enabled_by_owner"))
        verified = bool(info.get("isolation_verified"))
        live = bool(running and running.get(kind))
        if missing:
            status = "missing"
            summary = "Missing: " + ", ".join(missing) + "."
        elif not enabled:
            status = "off"
            summary = "Ready to enable. Owner permission is off."
        elif live:
            status = "ready"
            summary = ("Available. Isolation passed the attack-test probe (smoothcast --link-check --qualify)."
                       if verified else "Available. Isolation is set by your launcher; SmoothCast cannot verify it.")
        elif running is None:
            status = "restart"
            summary = "Enabled; restart the room to start the worker."
        else:
            status = "failed"
            summary = "Enabled but the room could not start the worker (check disk space and storage)."
        steps = [_LAUNCHER_HELP if name == LAUNCHER else _QUALIFY_STEP if name == _QUALIFY
                 else _INSTALL[system].get(name, "install " + name) for name in missing]
        if enabled and not verified and _QUALIFY not in missing:
            steps.append(_QUALIFY_STEP)
        out.append({"kind": kind, "label": LABELS[kind], "status": status,
                    "summary": summary, "repair": steps})
    return out


def subtitle(row: dict) -> str:
    """Compact line for a settings row: status plus the first repair step."""
    return row["summary"] + (" To fix: " + row["repair"][0] + "." if row["repair"] else "")


def describe_switches(owner, cfg: dict, switches: dict) -> None:
    """Set the two Preferences switch subtitles from PATH/file facts (never launches tools)."""
    import link_acquisition
    provider = link_acquisition.CommandProvider(
        kind for kind in ("youtube", "magnet") if cfg.get("portal_link_" + kind) is True)
    jobs = getattr(getattr(getattr(owner, "_portal", None), "server", None), "link_jobs", None)
    notes = {"youtube": "Authorised single videos only.", "magnet": "Authorised public torrents only."}
    for row in rows(provider.readiness(), running=jobs.capabilities() if jobs is not None else None):
        switches["portal_link_" + row["kind"]].set_subtitle(
            notes[row["kind"]] + " " + subtitle(row) + " Changes apply after a room restart.")
