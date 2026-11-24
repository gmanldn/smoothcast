"""Owner-facing availability of the isolated link workers (#588).

Pure and GTK-free: turns ``CommandProvider.readiness()`` plus what the running
room reports into one row per provider with a status (``ready``, ``off``,
``restart``, ``missing`` or ``failed``) and repair steps for the platform. It
only reads PATH/file facts already gathered by the provider; it never runs a
program, contacts a source or claims the isolation launcher is secure (the
application cannot attest that). Guests never need to install anything.
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
                  "processes and time; SmoothCast cannot supply or verify one yet")


def _platform(name: str | None) -> str:
    name = name or sys.platform
    return "win32" if name.startswith(("win", "cygwin")) else "darwin" if name == "darwin" else "linux"


def rows(readiness: dict, *, running: dict | None = None, platform: str | None = None) -> list[dict]:
    """One row per provider.

    ``running`` is the live room's ``LinkJobs.capabilities()`` (None when the
    room has no worker object, e.g. before a restart)."""
    system = _platform(platform)
    out = []
    for kind in ("youtube", "magnet"):
        info = readiness.get(kind, {})
        missing = list(info.get("missing", ()))
        enabled = bool(info.get("enabled_by_owner"))
        live = bool(running and running.get(kind))
        if missing:
            status = "missing"
            summary = "Missing: " + ", ".join(missing) + "."
        elif not enabled:
            status = "off"
            summary = "Ready to enable. Owner permission is off."
        elif live:
            status = "ready"
            summary = "Available. Isolation is set by your launcher; SmoothCast cannot verify it."
        elif running is None:
            status = "restart"
            summary = "Enabled; restart the room to start the worker."
        else:
            status = "failed"
            summary = "Enabled but the room could not start the worker (check disk space and storage)."
        steps = []
        for name in missing:
            steps.append(_LAUNCHER_HELP if name == LAUNCHER
                         else _INSTALL[system].get(name, "install " + name))
        out.append({"kind": kind, "label": LABELS[kind], "status": status,
                    "summary": summary, "repair": steps})
    return out


def subtitle(row: dict) -> str:
    """Compact line for a settings row: status plus the first repair step."""
    text = row["summary"]
    if row["repair"]:
        text += " To fix: " + row["repair"][0] + "."
    return text


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
