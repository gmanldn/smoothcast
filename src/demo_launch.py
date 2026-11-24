"""Launch the real app against the demo runtime (#454/#523). GTK-free.

``smoothcast --demo`` prepares :func:`demo_runtime.demo_runtime`, then starts
``src/cast_control.py`` as a child with the demo environment. It never looks
for, activates or stops the user's running SmoothCast: no single-instance
handoff, no installed-copy redirect, no D-Bus session. Network use is limited
to loopback by :mod:`demo_mode`.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping

import demo_runtime

ROOT = Path(__file__).resolve().parents[1]
# Never inherit another session's bus/portal: a bus would let this process
# find, activate or collide with the user's real SmoothCast or MPRIS player.
_DROP = ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "SMOOTHCAST_TEST_CONTEXT",
         "SMOOTHCAST_CAST_BACKEND", "SSH_AUTH_SOCK")


def is_demo_request(args: list[str]) -> bool:
    return any(arg == "--demo" or arg.startswith("--demo=") for arg in args)


def child_environment(base: Mapping[str, str], runtime: demo_runtime.DemoRuntime) -> dict[str, str]:
    env = {k: v for k, v in base.items() if k not in _DROP}
    env.update(runtime.environment())
    # HOME is the throwaway profile; keep the caller's user site-packages importable.
    import site
    env.setdefault("PYTHONUSERBASE", site.getuserbase())
    env["GDK_BACKEND"] = "x11"
    env["GSETTINGS_BACKEND"] = "memory"
    env["GTK_USE_PORTAL"] = "0"
    env["NO_AT_BRIDGE"] = "1"
    return env


def run(args: list[str], python: str | None = None, base_env: Mapping[str, str] | None = None, *,
        spawn: Callable[..., int] = subprocess.call, parent: Path | None = None,
        media_run: Callable[..., object] | None = None, extra: list[str] | None = None,
        out=None) -> int:
    """Start the demo. Only a bare ``--demo`` is accepted; returns the app's exit code."""
    out = out or sys.stderr
    if args != ["--demo"]:
        print("smoothcast --demo takes no other arguments; no receiver was contacted.", file=out)
        return 2
    import os
    base = dict(os.environ if base_env is None else base_env)
    if not base.get("DISPLAY"):
        print("Demo mode needs an X11 or XWayland display (DISPLAY is not set).", file=out)
        return 1
    import shutil
    if shutil.which("ffmpeg") is None and media_run is None:
        print("Demo mode generates sample media with FFmpeg, which was not found.", file=out)
        return 1
    try:
        with demo_runtime.demo_runtime(parent, run=media_run) as runtime:
            print("SmoothCast demo: isolated profile, fake receiver on loopback.", file=out, flush=True)
            command = [python or sys.executable, str(ROOT / "src" / "cast_control.py"), *(extra or [])]
            return int(spawn(command, cwd=ROOT, env=child_environment(base, runtime)))
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"SmoothCast demo could not start: {exc}", file=out)
        return 1


def smoke(seconds: float = 8.0) -> int:
    """Isolated-GUI check: the demo app must stay up ``seconds`` without crashing."""
    import os
    import shutil
    if shutil.which("ffmpeg") is None:
        print("demo smoke needs FFmpeg", file=sys.stderr)
        return 2
    with demo_runtime.demo_runtime() as runtime:
        process = subprocess.Popen([sys.executable, str(ROOT / "src" / "cast_control.py")], cwd=ROOT,
                                   env=child_environment(os.environ, runtime))
        try:
            code = process.wait(timeout=seconds)
            print(f"demo app exited early with {code}", file=sys.stderr)
            return code or 1
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            print("demo smoke: app stayed up", file=sys.stderr)
            return 0
