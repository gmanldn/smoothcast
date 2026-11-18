#!/usr/bin/env python3
"""One-shot GTK smoke test in an isolated Xvfb session; never steals focus.

Optional, manual/CI-only. Ordinary pytest remains pure Python and NEVER runs
this launcher. Refuses to run if Xvfb/xvfb-run/xauth are unavailable; there is
no fallback to DISPLAY or WAYLAND_DISPLAY from the developer's desktop.
"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MAX_SECONDS = 20


def isolated_environment(scratch: Path, parent: dict[str, str] | None = None) -> dict[str, str]:
    """Build an environment that cannot reach the user's display or XDG files."""
    env = dict(os.environ if parent is None else parent)
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                 "XAUTHORITY", "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION",
                 "SMOOTHCAST_TEST_CONTEXT"):
        env.pop(name, None)
    for key, subdir in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_RUNTIME_DIR", "runtime"),
    ):
        folder = scratch / subdir
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        env[key] = str(folder)
    env["GDK_BACKEND"] = "x11"
    env["GSETTINGS_BACKEND"] = "memory"
    env["NO_AT_BRIDGE"] = "1"
    env["GTK_USE_PORTAL"] = "0"
    env["SMOOTHCAST_GUI_TEST_ISOLATED"] = "1"
    return env


def main() -> int:
    if os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        print("GUI smoke tests are opt-in and must run outside pytest.",
              file=sys.stderr)
        return 2
    if sys.platform != "linux":
        print("Isolated GTK smoke test requires Linux/Xvfb.", file=sys.stderr)
        return 2
    needed = [name for name in ("Xvfb", "xvfb-run", "xauth") if not shutil.which(name)]
    if needed:
        print("GUI self-test skipped safely: missing " + ", ".join(needed)
              + ". Install xvfb and xauth; never use your desktop DISPLAY.",
              file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="smoothcast-xvfb-") as folder:
        scratch = Path(folder)
        env = isolated_environment(scratch)
        command = [
            shutil.which("xvfb-run"), "-a", "-s",
            "-screen 0 1280x800x24 -nolisten tcp",
            sys.executable, str(ROOT / "src" / "cast_control.py"), "--self-test",
        ]
        try:
            # Separate process group: on timeout kill both the child UI and
            # its Xvfb server. subprocess.run(timeout=...) only kills the
            # immediate xvfb-run shell and can leave children behind.
            process = subprocess.Popen(command, cwd=ROOT, env=env,
                                       start_new_session=True)
            try:
                return process.wait(timeout=MAX_SECONDS)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                print(f"GUI self-test exceeded {MAX_SECONDS}s; terminated.",
                      file=sys.stderr)
                return 124
        except OSError as exc:
            print(f"GUI self-test could not start: {exc}", file=sys.stderr)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())
