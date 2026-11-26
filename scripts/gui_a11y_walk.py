#!/usr/bin/env python3
"""Walk the real AT-SPI tree of the isolated GUI and fail on unnamed controls (#449).

Set SMOOTHCAST_A11Y_KEYS=1 to add an opt-in xdotool Tab walk (keyboard-only audit).
Run only through ``python3 scripts/test_gui_isolated.py --a11y`` (private Xvfb
and D-Bus session). The app is the normal ``--self-test`` window held open by
``selftest_hold``; this process reads it as an assistive technology would.
``find_unnamed`` is pure so the contract is testable without GTK."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
INTERACTIVE = frozenset({
    "push button", "toggle button", "check box", "radio button", "slider", "spin button",
    "switch", "combo box", "entry", "password text", "link", "menu item", "check menu item",
    "radio menu item", "page tab"})
MAX_NODES = 6000
MAX_DEPTH = 60


def find_unnamed(nodes: list[dict]) -> list[dict]:
    """Showing, enabled interactive nodes whose accessible name is empty."""
    return [n for n in nodes
            if n.get("role") in INTERACTIVE and n.get("showing") and not str(n.get("name", "")).strip()]


def check_tab_order(stops: list[dict], controls: list[dict]) -> list[str]:
    """Keyboard-only audit of Tab stops (in press order) against showing controls.
    Pure: flags a trap (no focus movement), a repeat before the cycle completes,
    and controls Tab never reached (excluding ones with a keyboard-less parent)."""
    problems: list[str] = []
    if not stops:
        return ["Tab never moved focus to any control"]
    seen: list[tuple] = []
    if len(stops) > 1 and stops[-1] == stops[-2]:
        problems.append(f"focus stuck on {stops[-1]['role']} {stops[-1]['name']!r}: Tab no longer moves")
    for stop in stops:
        key = (stop["role"], stop["name"], stop.get("x"), stop.get("y"))
        if key in seen:
            if seen.index(key) != 0:
                problems.append(f"focus loop skips back to {stop['name']!r} before the cycle ends")
            break
        seen.append(key)
    reached = {(k[0], k[1]) for k in seen}
    for control in controls:
        if (control["role"], control["name"]) not in reached:
            problems.append(f"not reachable by Tab: {control['role']} {control['name']!r}")
    return problems


def _focused(root):
    """The AT-SPI node holding keyboard focus under ``root``, with its position."""
    from gi.repository import Atspi
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        try:
            if node.get_state_set().contains(Atspi.StateType.FOCUSED):
                box = node.get_extents(Atspi.CoordType.WINDOW)
                return {"role": node.get_role_name() or "", "name": node.get_name() or "",
                        "x": box.x, "y": box.y}
            if depth < MAX_DEPTH:
                for index in range(node.get_child_count()):
                    child = node.get_child_at_index(index)
                    if child is not None:
                        stack.append((child, depth + 1))
        except Exception:  # noqa: BLE001
            continue
    return None


def _tab_stops(app, limit: int = 60) -> list[dict]:
    """Press Tab with xdotool in the private display, recording each focus stop."""
    xdotool = shutil.which("xdotool")
    if xdotool is None:
        return []
    # No window manager in the private display: give the app window X focus by hand.
    found = subprocess.run([xdotool, "search", "--onlyvisible", "--name", "."],
                           capture_output=True, text=True, timeout=10, check=False).stdout.split()
    if found:
        subprocess.run([xdotool, "windowfocus", found[-1]], timeout=10, check=False)
        time.sleep(0.5)
    subprocess.run([xdotool, "key", "Escape"], timeout=5, check=False)  # self-test leaves a modal dialog up
    time.sleep(0.5)
    stops: list[dict] = []
    for _ in range(limit):
        subprocess.run([xdotool, "key", "Tab"], timeout=5, check=False)
        time.sleep(0.25)
        stop = _focused(app)
        if stop is None:
            continue
        stops.append(stop)
        if len(stops) > 1 and stop == stops[-2]:
            break  # focus did not move: a keyboard trap, reported by check_tab_order
        if len(stops) > 1 and (stop["role"], stop["name"], stop["x"], stop["y"]) == (
                stops[0]["role"], stops[0]["name"], stops[0]["x"], stops[0]["y"]):
            break
    return stops


def _collect(root) -> list[dict]:
    from gi.repository import Atspi
    out: list[dict] = []
    stack = [(root, 0, "")]
    while stack and len(out) < MAX_NODES:
        node, depth, trail = stack.pop()
        try:
            states = node.get_state_set()
            name = node.get_name() or ""
            role = node.get_role_name() or ""
            out.append({"role": role, "name": name, "trail": trail[-120:],
                        "showing": states.contains(Atspi.StateType.SHOWING),
                        "enabled": states.contains(Atspi.StateType.ENABLED)})
            if depth < MAX_DEPTH:
                for index in range(node.get_child_count() - 1, -1, -1):
                    child = node.get_child_at_index(index)
                    if child is not None:
                        stack.append((child, depth + 1, f"{trail}/{role}:{name[:20]}"))
        except Exception as exc:  # noqa: BLE001 - a vanished node must not abort the walk
            out.append({"role": "error", "name": str(exc)[:80], "trail": trail[-120:], "showing": False})
    return out


def _app_nodes(scratch: Path, child_pid: int, wait: float = 20.0, stops: list | None = None) -> list[dict]:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    Atspi.init()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        desktop = Atspi.get_desktop(0)
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if app is not None and app.get_process_id() == child_pid and app.get_child_count() > 0:
                nodes = _collect(app)
                if stops is not None:  # keyboard-only pass, after the tree is read
                    stops.extend(_tab_stops(app))
                return nodes
        time.sleep(0.3)
    return []


BUS_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig><type>session</type><keep_umask/><listen>{address}</listen><auth>EXTERNAL</auth>
<servicedir>{services}</servicedir>
<policy context="default"><allow send_destination="*" eavesdrop="true"/><allow eavesdrop="true"/>
<allow own="*"/></policy></busconfig>
"""
A11Y_SERVICE = Path("/usr/share/dbus-1/services/org.a11y.Bus.service")


def _start_private_bus(scratch: Path):
    """Own session bus on a socket in the private runtime dir; only the AT-SPI
    service is activatable, so no portal or desktop service can start."""
    import gui_test_safety
    daemon = shutil.which("dbus-daemon")
    if daemon is None or not A11Y_SERVICE.is_file():
        print("A11Y skipped safely: missing dbus-daemon or AT-SPI bus service", file=sys.stderr)
        return None, ""
    services = scratch / "a11y-services"
    services.mkdir(exist_ok=True)
    (services / A11Y_SERVICE.name).write_bytes(A11Y_SERVICE.read_bytes())
    socket_path = scratch / gui_test_safety.PRIVATE_BUS_NAME
    address = f"unix:path={socket_path}"
    config = scratch / "a11y-bus.conf"
    config.write_text(BUS_CONFIG.format(address=address, services=services), encoding="utf-8")
    process = subprocess.Popen([daemon, f"--config-file={config}", "--nofork"],
                               env={k: v for k, v in os.environ.items() if k != "DBUS_SESSION_BUS_ADDRESS"})
    for _ in range(50):
        if socket_path.exists():
            return process, address
        time.sleep(0.1)
    process.kill()
    print("A11Y FAILED: private D-Bus did not start", file=sys.stderr)
    return None, ""


def main() -> int:
    if os.environ.get("SMOOTHCAST_GUI_TEST_ISOLATED") != "1":
        print("Refusing: run through scripts/test_gui_isolated.py --a11y", file=sys.stderr)
        return 2
    scratch = Path(os.environ["XDG_RUNTIME_DIR"])
    prefix = str(scratch / "a11y-hold")
    bus, address = _start_private_bus(scratch)
    if bus is None:
        return 2
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = address  # for this process's Atspi client
    env = dict(os.environ, SMOOTHCAST_A11Y_HOLD=prefix, GTK_A11Y="atspi")
    env.pop("NO_AT_BRIDGE", None)
    child = subprocess.Popen([sys.executable, str(ROOT / "src" / "cast_control.py"), "--self-test"],
                             cwd=ROOT, env=env)
    try:
        deadline = time.monotonic() + 60
        while not Path(prefix + ".ready").exists():
            if child.poll() is not None or time.monotonic() > deadline:
                print("A11Y FAILED: window never reached the hold point", file=sys.stderr)
                return 1
            time.sleep(0.2)
        stops: list[dict] | None = [] if os.environ.get("SMOOTHCAST_A11Y_KEYS") else None
        nodes = _app_nodes(scratch, child.pid, stops=stops)
    finally:
        Path(prefix + ".done").write_text("1", encoding="ascii")
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()
        bus.terminate()
    if not nodes:
        print("A11Y FAILED: no AT-SPI tree for the app (bridge not running?)", file=sys.stderr)
        return 1
    interactive = [n for n in nodes if n["role"] in INTERACTIVE and n["showing"]]
    bad = find_unnamed(nodes)
    print(f"A11Y: {len(nodes)} nodes, {len(interactive)} showing interactive controls, {len(bad)} unnamed")
    for node in interactive:
        print(f"A11Y control: {node['role']} / {node['name']!r}")
    for node in bad:
        print("A11Y UNNAMED:", json.dumps(node, sort_keys=True))
    keyboard_bad: list[str] = []
    if stops is not None:
        keyboard_bad = check_tab_order(stops, interactive)
        for stop in stops:
            print(f"KEYS stop: {stop['role']} / {stop['name']!r} @({stop['x']},{stop['y']})")
        for problem in keyboard_bad:
            print("KEYS PROBLEM:", problem)
    if os.environ.get("SMOOTHCAST_A11Y_DUMP"):
        Path(os.environ["SMOOTHCAST_A11Y_DUMP"]).write_text(json.dumps(nodes, indent=1), encoding="utf-8")
    return 1 if bad or keyboard_bad or not interactive else 0


if __name__ == "__main__":
    raise SystemExit(main())
