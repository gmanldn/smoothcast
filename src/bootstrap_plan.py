"""Read-only bootstrap preflight planner for virgin machines (#350). Pure; no network.

Given probed facts it returns the ordered steps ``--check`` would report and
setup would run: acquire Python, native packages, venv, runtime imports. Nothing
here escalates privileges itself; steps needing the OS package manager say so.
"""
from __future__ import annotations

MIN_PYTHON = (3, 10)
NATIVE = {  # platform -> (manager, packages)
    "linux-apt": ("apt-get", ["python3", "python3-venv", "python3-gi", "gir1.2-gtk-4.0", "gir1.2-adw-1",
                              "gstreamer1.0-plugins-base", "ffmpeg"]),
    "linux-dnf": ("dnf", ["python3", "python3-gobject", "gtk4", "libadwaita", "gstreamer1-plugins-base", "ffmpeg"]),
    "linux-pacman": ("pacman", ["python", "python-gobject", "gtk4", "libadwaita", "gst-plugins-base", "ffmpeg"]),
    "macos-brew": ("brew", ["python@3.12", "pygobject3", "gtk4", "libadwaita", "gstreamer", "ffmpeg"]),
    "windows-winget": ("winget", ["Python.Python.3.12", "Gyan.FFmpeg"]),
}
UNSAFE_PARTS = ("/", "/usr", "/bin", "/etc", "/System", "C:\\", "C:\\Windows", "C:\\Program Files")


def python_ok(version: tuple | None) -> bool:
    return bool(version) and tuple(version[:2]) >= MIN_PYTHON


def safe_destination(path: str, *, existing_foreign: bool = False) -> tuple[bool, str]:
    p = (path or "").strip()
    if not p or "\x00" in p:
        return False, "Choose an install folder."
    norm = p.rstrip("/\\") or p
    if norm in UNSAFE_PARTS or any(norm.lower().startswith(u.lower() + ("/" if "/" in u else "\\")) and u in ("/usr", "/bin", "/etc", "/System", "C:\\Windows", "C:\\Program Files") for u in UNSAFE_PARTS):
        return False, "That is a system folder. Pick a folder in your own account."
    if existing_foreign:
        return False, "That folder already holds another application. Pick an empty folder."
    return True, ""


def plan(facts: dict) -> dict:
    """facts: python(version tuple|None), manager(key|None), have(set of 'ffmpeg','gtk4','adwaita','gst'),
    venv_ok(bool), imports_ok(bool), online(bool), dest(str), dest_foreign(bool)."""
    steps, blockers = [], []
    ok, why = safe_destination(facts.get("dest", ""), existing_foreign=bool(facts.get("dest_foreign")))
    if not ok:
        blockers.append(why)
    manager = facts.get("manager")
    entry = NATIVE.get(manager) if manager else None
    have = set(facts.get("have") or ())
    if not python_ok(facts.get("python")):
        if entry is None:
            blockers.append("No supported package manager found to install Python 3.10 or newer.")
        else:
            steps.append({"id": "python", "action": f"{entry[0]} install Python", "needs_network": True, "needs_admin": manager != "windows-winget"})
    missing = [n for n in ("ffmpeg", "gtk4", "adwaita", "gst") if n not in have]
    if missing and entry is not None:
        steps.append({"id": "native", "action": f"{entry[0]} install {' '.join(entry[1])}", "needs_network": True,
                      "needs_admin": manager != "windows-winget", "missing": missing})
    elif missing:
        blockers.append("Missing: " + ", ".join(missing) + ". No package manager to install them.")
    if not facts.get("venv_ok"):
        steps.append({"id": "venv", "action": "create isolated virtual environment", "needs_network": False, "needs_admin": False})
    if not facts.get("imports_ok") or not facts.get("venv_ok"):
        steps.append({"id": "deps", "action": "install runtime dependencies from pyproject.toml", "needs_network": True, "needs_admin": False})
    if any(s["needs_network"] for s in steps) and facts.get("online") is False:
        blockers.append("No network connection. Connect, then run setup again.")
    steps.append({"id": "register", "action": "register shortcut and icon", "needs_network": False, "needs_admin": False})
    return {"ready": not blockers, "blockers": blockers, "steps": steps,
            "needs_admin": any(s["needs_admin"] for s in steps), "check_is_read_only": True}
