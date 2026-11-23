#!/usr/bin/env python3
"""Control-latency benchmark for the room portal (issue #466).

Models N phones on one room: N-1 background clients poll status like the web
remote does while one measured client taps play/pause, seek, volume and next.
For every tap we record

* **ack**       - time until the portal answers the POST (what the user feels
                  as "it registered"), and
* **confirmed** - time until /api/status shows the new receiver state.

The fake receiver confirms after ``receiver_ms`` (default 30 ms, a fast LAN
Chromecast), so the numbers isolate SmoothCast's own pipeline. Rate limits are
lifted for the run (they are tested elsewhere) so they cannot distort timing.
Standard library only; no GTK, no real receiver.

    python3 scripts/control_latency_benchmark.py --clients 1,8,32
    python3 scripts/control_latency_benchmark.py --write-baseline docs/control-latency-baseline.json
    python3 scripts/control_latency_benchmark.py --check docs/control-latency-baseline.json
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

SCENARIOS = ("play_pause", "seek", "volume", "next")
ACK_SLO_MS = 100.0          # tap -> acknowledged, p95
CONFIRM_SLO_MS = 1000.0     # tap -> receiver-confirmed state visible, p95
TOLERANCE = 0.20            # allowed p95 regression against the baseline
FLOOR_MS = 25.0             # ...but never tighter than baseline + 25 ms: below that is timer noise
SCHEMA = 1


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


class FakeReceiver:
    """Instantly accepts commands and confirms them after ``delay`` seconds."""

    def __init__(self, delay: float) -> None:
        self.delay, self._lock = delay, threading.Lock()
        self.state = {"state": "PLAYING", "title": "Film 0", "position": 0.0, "volume": 50,
                      "queue": [], "queue_revision": 0}
        self._tracks = 0

    def dispatch(self, action: str, payload: dict) -> object:
        if action == "status":
            with self._lock:
                return dict(self.state)
        timer = threading.Timer(self.delay, self._apply, (action, dict(payload)))
        timer.daemon = True
        timer.start()
        return "accepted"

    def _apply(self, action: str, payload: dict) -> None:
        with self._lock:
            if action == "play_pause":
                self.state["state"] = "PAUSED" if self.state["state"] == "PLAYING" else "PLAYING"
            elif action == "seek":
                self.state["position"] = float(payload.get("value", 0))
            elif action == "volume":
                self.state["volume"] = int(payload.get("value", 0))
            elif action == "next":
                self._tracks += 1
                self.state["title"] = f"Film {self._tracks}"


class Client:
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


def measure(clients: int, rounds: int, receiver_ms: float = 30.0) -> dict:
    """Run every scenario ``rounds`` times with ``clients`` phones in the room."""
    receiver = FakeReceiver(receiver_ms / 1000.0)
    server = portal._PortalHTTPServer(("127.0.0.1", 0), "000000", receiver.dispatch, pin_required=False)
    big = (1e6, 1e6)
    server.request_limiter = portal_commands.ParticipantRateLimiter(
        limits={"read": big, "mutation": big, "upload": big})
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    stop = threading.Event()
    try:
        tapper = Client(port, "Tapper")
        background = [Client(port, f"Phone {i}") for i in range(clients - 1)]

        def poll(client: Client) -> None:       # a phone left open on the Now Playing screen
            while not stop.wait(0.5):
                try:
                    client.state()
                except Exception:
                    pass
        threads = [threading.Thread(target=poll, args=(c,), daemon=True) for c in background]
        for thread in threads:
            thread.start()

        samples: dict[str, dict[str, list[float]]] = {s: {"ack": [], "confirm": []} for s in SCENARIOS}
        for index in range(rounds):
            before = tapper.state()
            plan = {
                "play_pause": ({"action": "play_pause"},
                               lambda s, b=before: s["state"] != b["state"]),
                "seek": ({"action": "seek", "value": 100 + index},
                         lambda s, i=index: s["position"] == 100 + i),
                "volume": ({"action": "volume", "value": 10 + (index * 7) % 80 + (index % 2)},
                           lambda s, i=index: s["volume"] == 10 + (i * 7) % 80 + (i % 2)),
                "next": ({"action": "next"}, lambda s, b=before: s["title"] != b["title"]),
            }
            for name, (body, confirmed) in plan.items():
                start = time.perf_counter()
                tapper.request("POST", "/api/action", body)
                acked = time.perf_counter()
                while True:
                    if confirmed(tapper.state()):
                        break
                    if time.perf_counter() - acked > 3.0:
                        raise RuntimeError(f"{name} was never confirmed")
                    time.sleep(0.005)
                done = time.perf_counter()
                samples[name]["ack"].append((acked - start) * 1000)
                samples[name]["confirm"].append((done - start) * 1000)
                time.sleep(0.02)
        stop.set()
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
    return {name: {"ack_p50": round(percentile(v["ack"], 0.5), 1), "ack_p95": round(percentile(v["ack"], 0.95), 1),
                   "confirm_p50": round(percentile(v["confirm"], 0.5), 1),
                   "confirm_p95": round(percentile(v["confirm"], 0.95), 1), "samples": len(v["ack"])}
            for name, v in samples.items()}


def run(client_counts: list[int], rounds: int, receiver_ms: float = 30.0) -> dict:
    return {"schema": SCHEMA, "receiver_ms": receiver_ms, "rounds": rounds,
            "profile": {"machine": platform.machine(), "python": platform.python_version()},
            "clients": {str(n): measure(n, rounds, receiver_ms) for n in client_counts}}


def evaluate(report: dict, baseline: dict | None = None, *, slack: float = 1.0) -> list[str]:
    """Problems: SLO breaches, and p95 regressions of more than 20 % over the baseline."""
    problems = []
    for count, scenarios in report["clients"].items():
        for name, row in scenarios.items():
            if row["ack_p95"] > ACK_SLO_MS * slack:
                problems.append(f"{name} @ {count} clients: ack p95 {row['ack_p95']} ms > {ACK_SLO_MS * slack:.0f} ms")
            if row["confirm_p95"] > CONFIRM_SLO_MS * slack:
                problems.append(f"{name} @ {count} clients: confirmed p95 {row['confirm_p95']} ms "
                                f"> {CONFIRM_SLO_MS * slack:.0f} ms")
            old = ((baseline or {}).get("clients", {}).get(count) or {}).get(name)
            for metric in ("ack_p95", "confirm_p95"):
                if old and row[metric] > max(old[metric] * (1 + TOLERANCE), old[metric] + FLOOR_MS) * slack:
                    problems.append(f"{name} @ {count} clients: {metric} regressed {old[metric]} -> "
                                    f"{row[metric]} ms (limit +{TOLERANCE:.0%})")
    return problems


def run_checked(client_counts: list[int], rounds: int, baseline: dict | None, *, slack: float = 1.0,
                receiver_ms: float = 30.0, attempts: int = 2) -> tuple[dict, list[str]]:
    """Measure; on a breach measure again. Only a regression that reproduces fails.

    With few samples a p95 is just the maximum, so a single scheduler hiccup can
    trip it; a genuine regression shows up in every run.
    """
    problems: list[str] = []
    report: dict = {}
    for _ in range(max(1, attempts)):
        report = run(client_counts, rounds, receiver_ms)
        problems = evaluate(report, baseline, slack=slack)
        if not problems:
            return report, []
    return report, problems


def table(report: dict) -> str:
    lines = ["clients  scenario    ack p50/p95 (ms)   confirmed p50/p95 (ms)"]
    for count, scenarios in report["clients"].items():
        for name, r in scenarios.items():
            lines.append(f"{count:>7}  {name:<10}  {r['ack_p50']:>6.1f} / {r['ack_p95']:<6.1f}   "
                         f"{r['confirm_p50']:>6.1f} / {r['confirm_p95']:<6.1f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--clients", default="1,8,32")
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--receiver-ms", type=float, default=30.0)
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--check", type=Path, help="fail on SLO breach or >20%% p95 regression")
    parser.add_argument("--slack", type=float, default=1.0)
    args = parser.parse_args(argv)
    counts = [int(c) for c in args.clients.split(",")]
    baseline = json.loads(args.check.read_text(encoding="utf-8")) if args.check else None
    if args.check:
        report, problems = run_checked(counts, args.rounds, baseline, slack=args.slack,
                                       receiver_ms=args.receiver_ms)
    else:
        report = run(counts, args.rounds, args.receiver_ms)
        problems = evaluate(report, None, slack=args.slack)
    print(table(report))
    if args.write_baseline:
        args.write_baseline.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline written to {args.write_baseline}")
    for problem in problems:
        print(f"LATENCY FAIL: {problem}", file=sys.stderr)
    return 1 if problems and (args.check or not args.write_baseline) else 0


if __name__ == "__main__":
    sys.exit(main())
