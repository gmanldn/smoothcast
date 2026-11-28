#!/usr/bin/env python3
"""Opt-in GUI behaviour checks in the private Xvfb session; never touches your desktop.

Where scripts/test_gui_isolated.py proves the window builds, this runs real GTK
widgets through a few user-visible behaviours (first-run receiver choice, the
Help > Report a problem action) using the same isolation: a disposable Xvfb
display, private XDG directories, no session bus and a one-use token. It never
scans the LAN, contacts a receiver or opens a browser (the launcher is patched).

    python3 scripts/gui_checks.py            # run every scenario
    python3 scripts/gui_checks.py first-run  # run one

Ordinary pytest never runs this. Linux with Xvfb, xvfb-run and xauth only.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_gui_isolated as isolation  # noqa: E402  (shared isolation helpers)

MAX_SECONDS = 40
DEMO_SECONDS = 120  # generates media, casts to the loopback fake receiver and stops it
JOURNEY_WIRE = ("LOAD", "PAUSE", "SEEK", "STOP")  # receiver-side commands the journey is judged on
# scenario -> contents of the seeded config.json (None: no config file at all)
SCENARIOS: dict[str, str | None] = {
    "local-video-runtime": None,
    "thumbnail-strip": None,
    "room-recovery": None,
    "first-run": None,
    "saved-device": '{"device": "Seeded TV"}\n',
    "report-problem": None,
    "picture-options": None,
    "aspect-override": None,
    "accent": None,
    "accent-saved": '{"accent": "violet"}\n',
    "accent-junk": '{"accent": "<script>"}\n',
    "density": None,
    "density-saved": '{"density": "spacious"}\n',
    "density-junk": '{"density": "<huge>"}\n',
    "subtitle-style": None,
    "subtitle-style-saved": '{"subtitle_style": "high-contrast"}\n',
    "subtitle-style-junk": '{"subtitle_style": "<invalid>"}\n',
    "text-fit": None,
    "audio-delay": None,
    "side-panel": None,
    "bookmarks": None,
    "network-view": None,
    "demo-journey": None,  # runs against the loopback fake receiver (demo runtime)
}


def parse_checks(output: str) -> list[tuple[str, str, bool, str]]:
    """(scenario, name, passed, detail) for every CHECK line the child printed."""
    parsed = []
    for line in output.splitlines():
        if not line.startswith("CHECK|"):
            continue
        parts = line.split("|", 4)   # the detail text may itself contain "|"
        if len(parts) == 5 and parts[3] in {"PASS", "FAIL"}:
            parsed.append((parts[1], parts[2], parts[3] == "PASS", parts[4]))
    return parsed


def journey_wire_checks(calls: list) -> list[tuple[str, str, bool, str]]:
    """What the fake receiver saw on the wire, in order: LOAD, PAUSE, SEEK, STOP."""
    seen = [str(data.get("type", "")) for _ns, data in calls]
    order = [t for t in seen if t in JOURNEY_WIRE]
    # A transcode seek restarts the stream at the new offset: a second LOAD
    # after the pause is as good a seek as a SEEK message.
    sought = "PAUSE" in order and ("SEEK" in order or "LOAD" in order[order.index("PAUSE"):])
    ok = bool(order) and order[0] == "LOAD" and order[-1] == "STOP" and sought
    return [("demo-journey", "receiver saw LOAD, PAUSE, a seek and STOP in order", ok, " ".join(order))]


def _demo_runtime(stack, env: dict[str, str], holder: dict):
    """Swap the scratch profile for the loopback demo runtime (isolated and token-gated)."""
    import site
    sys.path[:0] = [str(ROOT), str(ROOT / "src")]
    import demo_runtime
    from fakecast.receiver import FakeCastReceiver

    def factory(*args, **kwargs):
        holder["receiver"] = FakeCastReceiver(*args, **kwargs)
        return holder["receiver"]

    runtime = stack.enter_context(demo_runtime.demo_runtime(receiver_factory=factory))
    env.update(runtime.environment())
    env.setdefault("PYTHONUSERBASE", site.getuserbase())
    env.pop("SMOOTHCAST_CAST_BACKEND", None)
    marker = runtime.session.runtime_dir / ".smoothcast-gui-test-token"
    marker.write_text(env["SMOOTHCAST_GUI_TEST_TOKEN"], encoding="ascii")
    marker.chmod(0o600)
    env["SMOOTHCAST_DEMO_MEDIA"] = str(runtime.session.media_dir)


def run_scenario(name: str) -> tuple[int, list[tuple[str, str, bool, str]]]:
    scratch = Path(tempfile.mkdtemp(prefix="smoothcast-guicheck-"))
    demo = name == "demo-journey"
    holder: dict = {}
    try:
        with contextlib.ExitStack() as stack:
            env = isolation.isolated_environment(scratch)
            seed = SCENARIOS[name]
            if seed is not None:
                config_dir = Path(env["XDG_CONFIG_HOME"]) / "cast-control"
                config_dir.mkdir(parents=True, exist_ok=True)
                (config_dir / "config.json").write_text(seed, encoding="utf-8")
            if demo:
                _demo_runtime(stack, env, holder)
            limit = DEMO_SECONDS if demo else MAX_SECONDS
            command = [shutil.which("xvfb-run") or "xvfb-run", "-a", "-s",
                       "-screen 0 1280x800x24 -nolisten tcp",
                       sys.executable, str(ROOT / "scripts" / "gui_checks_child.py"), name]
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                out, err = process.communicate(timeout=limit)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                out, err = process.communicate()
                print(f"[{name}] exceeded {limit}s; terminated", file=sys.stderr)
                return 124, parse_checks(out)
            if process.returncode not in (0, 1) and err.strip():
                print(f"[{name}] child stderr:\n{err.strip()[-1500:]}", file=sys.stderr)
            checks = parse_checks(out)
            if demo:
                checks += journey_wire_checks(holder["receiver"].calls)
            return process.returncode, checks
    finally:
        isolation.discard_scratch(scratch)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        print("GUI checks are opt-in and must run outside pytest.", file=sys.stderr)
        return 2
    if sys.platform != "linux":
        print("GUI checks require Linux/Xvfb.", file=sys.stderr)
        return 2
    missing = [n for n in ("Xvfb", "xvfb-run", "xauth") if not shutil.which(n)]
    if missing:
        print("GUI checks skipped safely: missing " + ", ".join(missing)
              + ". Install xvfb and xauth; never use your desktop DISPLAY.", file=sys.stderr)
        return 2
    chosen = args or list(SCENARIOS)
    unknown = [n for n in chosen if n not in SCENARIOS]
    if unknown:
        print(f"unknown scenario(s): {', '.join(unknown)}; choose from {', '.join(SCENARIOS)}", file=sys.stderr)
        return 2
    failures = 0
    for name in chosen:
        code, checks = run_scenario(name)
        for _scenario, check, passed, detail in checks:
            print(f"  {'PASS' if passed else 'FAIL'}  [{name}] {check}" + ("" if passed or not detail else f"  -> {detail}"))
        bad = [c for c in checks if not c[2]]
        if code not in (0,) or bad or not checks:
            failures += 1
            print(f"[{name}] FAILED (exit {code}, {len(bad)} failing, {len(checks)} checks)")
        else:
            print(f"[{name}] ok ({len(checks)} checks)")
    print("GUI checks " + ("FAILED" if failures else "passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
