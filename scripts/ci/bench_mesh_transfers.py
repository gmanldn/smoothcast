#!/usr/bin/env python3
"""Deterministic loopback transfer benchmark smoke for #573."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import platform
import random
import shutil
import sys
import tempfile
from pathlib import Path
from threading import Thread
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import transfer_metrics

SIZES = {"64k": 64 * 1024, "2m": 2 * 1024**2, "64m": 64 * 1024**2,
         "1g": 1024**3}
SCENARIOS = ("browser-upload-node", "node-copy", "node-range-receiver",
             "relay-browser", "progressive-playing", "guests-playing")
CHUNK = 64 * 1024


def payload(size: int, seed: int) -> bytes:
    rng = random.Random(seed)
    return rng.randbytes(size)


class Handler(BaseHTTPRequestHandler):
    def do_PUT(self):
        time.sleep(self.server.rtt_ms / 1000)
        self.server.received = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        body = self.server.received
        header = self.headers.get("Range")
        if header:
            start, end = map(int, header.removeprefix("bytes=").split("-", 1))
            body = body[start:end + 1]
            self.send_response(206)
        else:
            self.send_response(200)
        time.sleep(self.server.rtt_ms / 1000)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        for offset in range(0, len(body), CHUNK):
            piece = body[offset:offset + CHUNK]
            self.wfile.write(piece)
            self.wfile.flush()
            if self.server.bandwidth_mbps:
                time.sleep(len(piece) * 8 / (self.server.bandwidth_mbps * 1_000_000))

    def log_message(self, *_args):
        pass


def server(rtt_ms: float, bandwidth_mbps: float):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.received = b""
    instance.rtt_ms = rtt_ms
    instance.bandwidth_mbps = bandwidth_mbps
    thread = Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    return instance, thread, f"http://127.0.0.1:{instance.server_port}"


def run_scenario(name: str, data: bytes, clients: int, rtt_ms: float, bandwidth_mbps: float) -> dict:
    origin, origin_thread, origin_url = server(rtt_ms, bandwidth_mbps)
    destination, dest_thread, dest_url = server(rtt_ms, bandwidth_mbps)
    latencies, delivered = [], []
    started = time.perf_counter()
    first_byte = None
    try:
        with tempfile.TemporaryDirectory(prefix="smoothcast-bench-") as directory:
            source = Path(directory) / "source"
            source.write_bytes(data)
            if name == "node-copy":
                target = Path(directory) / "copy"
                begin = time.perf_counter()
                shutil.copyfile(source, target)
                latencies.append((time.perf_counter() - begin) * 1000)
                received = target.read_bytes()
                expected = data
            else:
                upload_url = origin_url
                if name == "relay-browser":
                    upload_url = dest_url
                request = urllib.request.Request(upload_url, data=data, method="PUT")
                begin = time.perf_counter()
                with urllib.request.urlopen(request, timeout=60) as response:
                    response.read()
                latencies.append((time.perf_counter() - begin) * 1000)

                if name == "node-range-receiver":
                    request = urllib.request.Request(origin_url, headers={
                        "Range": f"bytes=0-{min(len(data), CHUNK) - 1}"})
                    with urllib.request.urlopen(request, timeout=60) as response:
                        received = response.read()
                    expected = data[:CHUNK]
                elif name == "relay-browser":
                    with urllib.request.urlopen(dest_url, timeout=60) as response:
                        received = response.read()
                    expected = data
                elif name in {"guests-playing", "progressive-playing"}:
                    def fetch(_index):
                        began = time.perf_counter()
                        with urllib.request.urlopen(origin_url, timeout=60) as response:
                            first = response.read(CHUNK)
                            elapsed_first = time.perf_counter() - began
                            rest = response.read()
                        return first + rest, elapsed_first, (time.perf_counter() - began) * 1000
                    with ThreadPoolExecutor(max_workers=clients) as pool:
                        results = list(pool.map(fetch, range(clients)))
                    received = results[0][0]
                    first_byte = min(result[1] for result in results)
                    latencies.extend(result[2] for result in results)
                    delivered.extend(len(result[0]) for result in results)
                    expected = data
                else:
                    with urllib.request.urlopen(origin_url, timeout=60) as response:
                        received = response.read()
                    expected = data
            corrupt = sum(a != b for a, b in zip(received, expected)) + abs(len(received)-len(expected))
            if hashlib.sha256(received).digest() != hashlib.sha256(expected).digest():
                corrupt = max(1, corrupt)
            if name not in {"guests-playing", "progressive-playing"}:
                delivered.append(len(received))
            elapsed = time.perf_counter() - started
            record = {"bytes": sum(delivered), "elapsed_s": elapsed,
                      "ttfb_s": first_byte, "playable_s": first_byte,
                      "chunk_ms": latencies, "per_client_bytes": delivered,
                      "corrupt_bytes": corrupt, "stalls": 0,
                      "fds_before": 0, "fds_after": 0}
            summary = transfer_metrics.summarise(record)
            return {"scenario": name, "summary": summary,
                    "bottleneck_hypothesis": transfer_metrics.bottleneck(record),
                    "invariants": transfer_metrics.invariants(summary)}
    finally:
        for instance, thread in ((origin, origin_thread), (destination, dest_thread)):
            instance.shutdown()
            instance.server_close()
            thread.join(timeout=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=(*SIZES, "all"), default="2m")
    parser.add_argument("--scenario", choices=(*SCENARIOS, "all"), default="all")
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--seed", type=int, default=573)
    parser.add_argument("--rtt-ms", type=float, choices=(0, .1, 1, 10, 100), default=0)
    parser.add_argument("--bandwidth-mbps", type=float, default=0, help="0 means unshaped")
    parser.add_argument("--baseline", type=Path, help="compare against prior JSON report")
    parser.add_argument("--tolerance", type=float, default=.25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.clients <= 64:
        parser.error("--clients must be in 1..64")
    if args.bandwidth_mbps < 0 or not 0 <= args.tolerance < 1:
        parser.error("bandwidth must be nonnegative and tolerance in [0, 1)")
    sizes = SIZES if args.size == "all" else {args.size: SIZES[args.size]}
    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    runs = [run_scenario(scenario, payload(size, args.seed), args.clients, args.rtt_ms, args.bandwidth_mbps)
            for size in sizes.values() for scenario in scenarios]
    report = {"schema": 1, "machine": platform.platform(), "python": platform.python_version(),
              "seed": args.seed, "size_bytes": sizes, "runs": runs}
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        prior = {run["scenario"]: run["summary"] for run in baseline.get("runs", [])}
        for run in runs:
            old = prior.get(run["scenario"])
            run["baseline_regressions"] = transfer_metrics.compare(old, run["summary"], args.tolerance) if old else []
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return int(any(run["invariants"] or run.get("baseline_regressions") for run in runs))


if __name__ == "__main__":
    raise SystemExit(main())
