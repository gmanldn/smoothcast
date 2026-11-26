#!/usr/bin/env python3
"""Cross-surface freshness benchmark (#629): desktop ⇄ web within a bound.

Models one room with a fake receiver and an authoritative desktop owner over a
real loopback portal, with no GTK, no TV and no real receiver. It measures

* **desktop_to_web** - the desktop changes authoritative state and publishes; the
  time until a web ``GET /api/status`` reflects the change with a newer
  ``snapshot_version``.
* **web_to_desktop** - a web ``POST /api/action`` is applied; the time until the
  desktop's authoritative state reflects it *and* the served snapshot reflects it
  too (no stale read afterwards).

Both bounds are 500 ms. Standard library only; the gate mirrors the #466
control-latency gate and runs in the same opt-in CI lane.

    python3 scripts/freshness_benchmark.py --rounds 12
    python3 scripts/freshness_benchmark.py --write-baseline docs/cross-surface-freshness-baseline.json
    python3 scripts/freshness_benchmark.py --check docs/cross-surface-freshness-baseline.json
"""
from __future__ import annotations

import argparse
from http.client import HTTPConnection
import json
import math
from pathlib import Path
import platform
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import portal  # noqa: E402
import portal_commands  # noqa: E402
import portal_status  # noqa: E402

DIRECTIONS = ("desktop_to_web", "web_to_desktop")
SLO_MS = 500.0          # either direction reaches the other surface within this
TOLERANCE = 0.20        # allowed p95 regression against the baseline
FLOOR_MS = 50.0         # ...but never tighter than baseline + 50 ms: below that is noise
TIMEOUT_SECONDS = 3.0   # a change that never lands is a hard failure, not a slow sample
SCHEMA = 1


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


class Room:
    """One loopback portal plus the desktop that owns the authoritative state."""

    PIN = "000000"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.snapshot = portal_status.PublishedStatus()
        self.fence = portal_commands.CommandFence()
        self._state = {
            "title": "Living-room film", "state": "PLAYING",
            "state_label": "Playing", "state_short": "Playing",
            "state_description": "Media is playing on the receiver",
            "state_icon": "media-playback-start-symbolic",
            "receiver": "Living Room TV", "position": 0.0, "duration": 300.0,
            "media_kind": "video", "rate": 1.0, "volume": 50,
            "queue": [{"id": "item-1", "title": "track-1.mp3", "duration": 30.0}],
            "queue_revision": 0, "library_copies": [], "active": True, "busy": False,
            "preparing": False, "can_stop": True, "can_play_pause": True, "can_seek": True,
            "music_autogain": False, "accent": "default", "network_activity": [],
            "cast_feedback": None,
        }
        self.server = portal._PortalHTTPServer(
            ("127.0.0.1", 0), self.PIN, self.dispatch, pin_required=False,
            status_snapshot=self.snapshot.read, fence=self.fence)
        self.server.status_peek = self.snapshot.peek
        big = (1e6, 1e6)
        self.server.request_limiter = portal_commands.ParticipantRateLimiter(
            limits={"read": big, "mutation": big, "upload": big})
        self.port = self.server.server_address[1]
        self._thread: threading.Thread | None = None
        self._publish()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self._thread is not None:
            self._thread.join(3)

    def _publish(self) -> None:
        state = dict(self._state)
        session_id, revision, _owner = self.fence.snapshot()
        state["session_id"], state["revision"] = session_id, revision
        self.snapshot.publish(state)

    def _apply(self, action: str, payload: dict) -> None:
        if action == "play_pause":
            self._state["state"] = "PAUSED" if self._state["state"] == "PLAYING" else "PLAYING"
        elif action == "seek":
            self._state["position"] = float(payload.get("value", 0.0))
        elif action == "volume":
            self._state["volume"] = int(payload.get("value", 0))
        elif action == "music_autogain":
            self._state["music_autogain"] = bool(payload.get("value"))
        elif action == "next":
            self._state["queue_revision"] += 1
        else:
            raise portal.PortalRequestError(400, "Unsupported action")

    def dispatch(self, action: str, payload: dict) -> object:
        """Apply a web-originated mutation, then publish the desktop state."""
        if action == "status":
            with self._lock:
                return dict(self._state)
        with self._lock:
            self._apply(action, payload)
            self._publish()
        return "accepted"

    def desktop_act(self, action: str, payload: dict | None = None) -> None:
        """The owner/desktop changes authoritative state and publishes it."""
        with self._lock:
            self._apply(action, payload or {})
            self.fence.rotate()
            self._publish()

    def view(self) -> dict:
        with self._lock:
            return dict(self._state)


class Client:
    """An authenticated web remote over loopback, like the browser room does."""

    def __init__(self, port: int, name: str) -> None:
        self.port, self.host = port, f"127.0.0.1:{port}"
        self.cookie = self.csrf = ""
        reply = self.request("POST", "/api/login", {"name": name})
        self.csrf = reply["csrf"]

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": self.host, "Origin": f"http://{self.host}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            reply = conn.getresponse()
            raw = reply.read()
            cookie = reply.getheader("Set-Cookie")
            if cookie:
                self.cookie = cookie.split(";", 1)[0]
            if reply.status >= 400:
                raise RuntimeError(f"{method} {path} -> {reply.status}")
            return json.loads(raw) if raw else {}
        finally:
            conn.close()

    def state(self) -> dict:
        return self.request("GET", "/api/status")["state"]

    def action(self, body: dict) -> None:
        self.request("POST", "/api/action", body)


def measure(rounds: int) -> dict:
    """Round-trip every direction ``rounds`` times over one live room."""
    room = Room()
    room.start()
    samples: dict[str, list[float]] = {name: [] for name in DIRECTIONS}
    try:
        client = Client(room.port, "Web Remote")
        for index in range(rounds):
            before = client.state()
            target = (before["volume"] + 10 + index) % 101
            start = time.perf_counter()
            room.desktop_act("volume", {"value": target})
            _await(client, start, lambda state, t=target: (
                state["volume"] == t and state["snapshot_version"] > before["snapshot_version"]),
                "the desktop change never reached the web snapshot")
            samples["desktop_to_web"].append((time.perf_counter() - start) * 1000)

            before = client.state()
            position = float(before["position"] + 5.0)
            start = time.perf_counter()
            client.action({"action": "seek", "value": position})
            _await(client, start, lambda state, p=position: (
                room.view()["position"] == p and state["position"] == p
                and state["snapshot_version"] > before["snapshot_version"]),
                "the web change never reached the desktop state")
            samples["web_to_desktop"].append((time.perf_counter() - start) * 1000)
            time.sleep(0.01)
    finally:
        room.stop()
    return {name: {"p50": round(percentile(values, 0.5), 1),
                   "p95": round(percentile(values, 0.95), 1),
                   "samples": len(values)}
            for name, values in samples.items()}


def _await(client: "Client", start: float, confirmed, message: str) -> None:
    """Poll until ``confirmed`` or the hard timeout; a breach must reproduce."""
    deadline = start + TIMEOUT_SECONDS
    while True:
        if confirmed(client.state()):
            return
        if time.perf_counter() > deadline:
            raise RuntimeError(message)
        time.sleep(0.002)


def run(rounds: int) -> dict:
    return {"schema": SCHEMA, "rounds": rounds,
            "profile": {"machine": platform.machine(), "python": platform.python_version()},
            "directions": measure(rounds)}


def evaluate(report: dict, baseline: dict | None = None, *, slack: float = 1.0) -> list[str]:
    """Problems: bound breaches, and p95 regressions of more than 20 % over the baseline."""
    problems = []
    for name, row in report["directions"].items():
        if row["p95"] > SLO_MS * slack:
            problems.append(f"{name}: p95 {row['p95']} ms > {SLO_MS * slack:.0f} ms")
        old = ((baseline or {}).get("directions", {}).get(name)) or {}
        if old.get("p95") and row["p95"] > max(old["p95"] * (1 + TOLERANCE),
                                                old["p95"] + FLOOR_MS) * slack:
            problems.append(f"{name}: p95 regressed {old['p95']} -> {row['p95']} ms "
                            f"(limit +{TOLERANCE:.0%})")
    return problems


def run_checked(rounds: int, baseline: dict | None, *, slack: float = 1.0,
                attempts: int = 2) -> tuple[dict, list[str]]:
    """Measure; on a breach measure again, so only a reproducible breach fails."""
    problems: list[str] = []
    report: dict = {}
    for _ in range(max(1, attempts)):
        report = run(rounds)
        problems = evaluate(report, baseline, slack=slack)
        if not problems:
            return report, []
    return report, problems


def table(report: dict) -> str:
    lines = ["direction         p50 (ms)   p95 (ms)   samples"]
    for name, row in report["directions"].items():
        lines.append(f"{name:<16}  {row['p50']:>7.1f}   {row['p95']:>7.1f}   {row['samples']:>7}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--check", type=Path, help="fail on a bound breach or >20%% p95 regression")
    parser.add_argument("--slack", type=float, default=1.0)
    args = parser.parse_args(argv)
    baseline = json.loads(args.check.read_text(encoding="utf-8")) if args.check else None
    if args.check:
        report, problems = run_checked(args.rounds, baseline, slack=args.slack)
    else:
        report = run(args.rounds)
        problems = evaluate(report, None, slack=args.slack)
    print(table(report))
    if args.write_baseline:
        args.write_baseline.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
        print(f"baseline written to {args.write_baseline}")
    for problem in problems:
        print(f"FRESHNESS FAIL: {problem}", file=sys.stderr)
    return 1 if problems and (args.check or not args.write_baseline) else 0


if __name__ == "__main__":
    sys.exit(main())
