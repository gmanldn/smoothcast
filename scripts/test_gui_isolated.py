#!/usr/bin/env python3
"""One-shot GTK smoke test in an isolated Xvfb session; never steals focus.

Optional, manual/CI-only. Ordinary pytest remains pure Python and NEVER runs
this launcher. Refuses to run if Xvfb/xvfb-run/xauth are unavailable; there is
no fallback to DISPLAY or WAYLAND_DISPLAY from the developer's desktop.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time

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
    # The private marker prevents accidental GUI activation if a caller
    # inherits the testing flag in a live shell. Xvfb-run supplies XAUTHORITY.
    token = secrets.token_hex(32)
    marker = Path(env["XDG_RUNTIME_DIR"]) / ".smoothcast-gui-test-token"
    marker.write_text(token, encoding="ascii")
    marker.chmod(0o600)
    env["SMOOTHCAST_GUI_TEST_TOKEN"] = token
    return env


def seed_isolated_state(scratch: Path, env: dict[str, str]) -> dict[str, Path]:
    """Plant a saved cast and an expired sleep timer in the private home.

    The window must build without adopting the cast, scanning the LAN or
    consuming the timer; the seeded files must be left byte-identical.
    """
    config_dir = Path(env["XDG_CONFIG_HOME"]) / "cast-control"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = config_dir / "config.json"
    config.write_text(
        '{"device": "Seeded TV", "sleep_timer_minutes": 30,'
        ' "sleep_timer_deadline": 1.0}\n',
        encoding="utf-8",
    )
    session_dir = Path(env["HOME"]) / ".cache" / "cast-control"
    session_dir.mkdir(parents=True, exist_ok=True)
    session = session_dir / "session.json"
    session.write_text(
        '{"file": "/seeded/film.mkv", "mode": "transcode", "offset": 0,'
        ' "duration": 10, "device": "Seeded TV", "title": "Seeded Film"}\n',
        encoding="utf-8",
    )
    return {"config": config, "session": session}


def discard_scratch(folder: Path | str) -> None:
    """Remove the isolated scratch tree, tolerating writers that outlive Xvfb.

    A Mesa shader-cache helper can still be flushing when the smoke test
    finishes, which makes the removal fail with "Directory not empty" on an
    otherwise successful run. Retry briefly, then never let leftover scratch
    turn a green verification into a failed one.
    """
    for _ in range(3):
        try:
            shutil.rmtree(folder)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.2)
    shutil.rmtree(folder, ignore_errors=True)


def main() -> int:
    demo = sys.argv[1:] == ["--demo"]
    interaction = sys.argv[1:] == ["--interaction"]
    a11y = sys.argv[1:] == ["--a11y"]  # AT-SPI tree walk of the real window (#449)
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
    folder = tempfile.mkdtemp(prefix="smoothcast-xvfb-")
    try:
        scratch = Path(folder)
        env = isolated_environment(scratch)
        seeded = seed_isolated_state(scratch, env)
        samples = scratch / "interaction-samples.json"
        if interaction:
            env["SMOOTHCAST_INTERACTION_SAMPLES"] = str(samples)
        before = {name: path.read_bytes() for name, path in seeded.items()}
        command = [
            shutil.which("xvfb-run"), "-a", "-s",
            "-screen 0 1280x800x24 -nolisten tcp",
            sys.executable, str(ROOT / "src" / "cast_control.py"), "--self-test",
        ]
        if a11y:  # the walker starts its own private session bus; never the user's
            command[-3:] = [sys.executable, str(ROOT / "scripts" / "gui_a11y_walk.py")]
            env.pop("NO_AT_BRIDGE", None)
            env["GTK_A11Y"] = "atspi"
        if demo:  # demo mode end to end inside the disposable display (#454)
            import site
            env.setdefault("PYTHONUSERBASE", site.getuserbase())
            command[-2:] = ["-c", "import sys; sys.path.insert(0, 'src'); "
                            "import demo_launch; sys.exit(demo_launch.smoke())"]
        try:
            # Separate process group: on timeout kill both the child UI and
            # its Xvfb server. subprocess.run(timeout=...) only kills the
            # immediate xvfb-run shell and can leave children behind.
            process = subprocess.Popen(command, cwd=ROOT, env=env,
                                       start_new_session=True)
            limit = 120 if interaction or (a11y and os.environ.get("SMOOTHCAST_A11Y_KEYS")) else MAX_SECONDS
            try:
                code = process.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                print(f"GUI self-test exceeded {limit}s; terminated.",
                      file=sys.stderr)
                return 124
            after = {name: path.read_bytes() for name, path in seeded.items()}
            if demo:
                return code
            if interaction:
                if not samples.is_file():
                    print("interaction benchmark produced no samples", file=sys.stderr)
                    return 1
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "interaction_latency_benchmark", ROOT / "scripts" / "interaction_latency_benchmark.py")
                bench = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(bench)
                payload = json.loads(samples.read_text(encoding="utf-8"))
                print(bench.table(bench.summarize(payload)))
                keep = os.environ.get("SMOOTHCAST_INTERACTION_KEEP")
                if keep:
                    shutil.copyfile(samples, keep)
                    print(f"INTERACTION: samples kept at {keep}")
                return 0
            changed = [name for name in before if before[name] != after[name]]
            if changed:
                print("GUI self-test touched seeded state: " + ", ".join(changed),
                      file=sys.stderr)
                return 3
            return code
        except OSError as exc:
            print(f"GUI self-test could not start: {exc}", file=sys.stderr)
            return 2
    finally:
        discard_scratch(folder)


if __name__ == "__main__":
    raise SystemExit(main())
