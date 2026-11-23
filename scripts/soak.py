#!/usr/bin/env python3
"""Accelerated soak: does the room leak threads, descriptors, memory or map entries? (#464)

Runs N cycles against the real portal (loopback, fake receiver) with 31 polling
phones plus a visitor (the room caps at 32), a 500-item queue, seeks, votes, queue edits, uploads and phones joining
and leaving. A fake clock advances 30 s per cycle, so 2,000 cycles are ~17
simulated hours: sessions expire and re-join, the command cache and limiter
turn over. Every 10 cycles it samples threads, open FDs, RSS, scratch files and
the size of every bounded in-memory map. After a 20% warm-up threads and FDs must
not grow at all and every bounded map must stay under its designed cap; RSS and
upload retention only warn, because a hard gate must never be flaky.

    python3 scripts/soak.py --cycles 150               # a minute: smoke
    python3 scripts/soak.py --cycles 2000 --report soak-report.json   # nightly
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

SAMPLE_EVERY = 10
POLLS_PER_CYCLE = 10          # a rotating subset: every phone polls every ~3 cycles
WARMUP = 0.2
SECONDS_PER_CYCLE = 30.0
PHONES = 31                  # + 1 visiting guest = the room's 32-participant cap
QUEUE = 500
STRICT_METRICS = ("threads", "fds")          # must not grow at all once warm
# Designed caps of the bounded in-memory maps: a map may fill up to its cap during
# the run (that is what bounded means) but must never exceed it.
CAPS = {"sessions": 128, "participants": 32, "dormant": 128, "events": 200, "command_cache": 512,
        "attempts": 512, "lockouts": 512, "limiter": 512, "screens": 8, "votes": QUEUE + 100}
# Reported, not gated: completed uploads stay on disk while their queue items do, and
# this harness's fake dispatcher never frees them.
INFORMATIONAL = ("uploads", "files")


def _reference_and_tail(values: list[float]) -> tuple[float, float]:
    third = max(1, len(values) // 3)
    return max(values[:third]), max(values[-third:])


def verdict(samples: list[dict], *, warmup: float = WARMUP, rss_tolerance: float = 0.05,
            caps: dict[str, int] | None = None) -> dict:
    """Pure pass/fail. Threads and FDs: no growth after warm-up. Bounded maps: never over cap."""
    caps = CAPS if caps is None else caps
    skip = int(len(samples) * warmup)
    kept = samples[skip:]
    failures: list[str] = []
    warnings: list[str] = []
    if len(kept) < 3:
        return {"verdict": "fail", "failures": ["too few samples to judge"], "warnings": [],
                "samples": len(samples), "judged": len(kept), "growth": {}}
    growth: dict[str, float] = {}
    for name in STRICT_METRICS:
        values = [s[name] for s in kept if s.get(name) is not None]
        if len(values) >= 3:
            reference, tail = _reference_and_tail(values)
            growth[name] = tail - reference
            if tail > reference:
                failures.append(f"{name} grew from {reference:g} to {tail:g} after warm-up")
    for name in kept[0]["maps"]:
        values = [s["maps"][name] for s in kept]
        reference, tail = _reference_and_tail(values)
        growth[f"map:{name}"] = tail - reference
        cap = caps.get(name)
        if cap is not None and max(values) > cap:
            failures.append(f"map {name} reached {max(values)}, over its cap of {cap}")
        elif cap is None and name not in INFORMATIONAL and tail > reference:
            failures.append(f"uncapped map {name} grew from {reference:g} to {tail:g} after warm-up")
    for name in INFORMATIONAL:
        values = [s["maps"].get(name, s.get(name, 0)) for s in kept]
        if values and values[-1] > values[0]:
            warnings.append(f"{name} grew {values[0]} -> {values[-1]} (informational: follows queued uploads)")
    rss = [s["rss_kb"] for s in kept if s.get("rss_kb")]
    if len(rss) >= 3:
        before = statistics.median(rss[:max(1, len(rss) // 3)])
        after = statistics.median(rss[-max(1, len(rss) // 3):])
        growth["rss_kb"] = after - before
        if after > before * (1 + rss_tolerance):
            warnings.append(f"RSS median grew {before:.0f} -> {after:.0f} kB (> {rss_tolerance:.0%}); "
                            "warning only, allocators are noisy")
    return {"verdict": "fail" if failures else "pass", "failures": failures, "warnings": warnings,
            "samples": len(samples), "judged": len(kept), "growth": growth}


def _fds() -> int | None:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def _rss_kb() -> int | None:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 1024
    except (OSError, ValueError, IndexError):
        return None


def settle(timeout: float = 1.0, stable_reads: int = 4, interval: float = 0.02) -> None:
    """Wait until the thread count stops moving, so a normal in-flight request thread
    (response sent, handler not yet exited) is not mistaken for a leak.

    A leaked thread never exits, so it is still counted afterwards and shows up as
    growth between samples. Python-version agnostic: no thread-name assumptions.
    """
    deadline = time.monotonic() + timeout
    last, steady = threading.active_count(), 1
    while steady < stable_reads and time.monotonic() < deadline:
        time.sleep(interval)
        now = threading.active_count()
        steady, last = (steady + 1, now) if now == last else (1, now)


def sample(cycle: int, harness, upload_root: Path) -> dict:
    settle()
    server = harness.server
    return {"cycle": cycle, "threads": threading.active_count(), "fds": _fds(), "rss_kb": _rss_kb(),
            "files": sum(1 for _ in upload_root.rglob("*") if _.is_file()),
            "maps": {"sessions": len(server._sessions), "participants": len(server.room.participants),
                     "dormant": len(server.room._dormant), "votes": len(server.room.votes),
                     "events": len(server.room.events), "command_cache": len(server._queue_command_cache),
                     "attempts": len(server._attempts), "lockouts": len(server._lockouts),
                     "limiter": len(server.request_limiter._buckets), "uploads": len(server.uploads._uploads),
                     "screens": len(server.screens._screens)}}


def run(cycles: int, *, hooks=(), report_path: Path | None = None, quiet: bool = False) -> dict:
    """Run the soak and return {'verdict': ..., 'samples': [...], 'counts': {...}}."""
    import portal_commands
    import portal_uploads
    import streamer
    from test_room_conformance import RoomHarness

    clock = SimpleNamespace(now=1000.0)
    tick = lambda: clock.now  # noqa: E731
    counts = {"seeks": 0, "joins": 0, "uploads": 0, "polls": 0, "votes": 0, "queue_edits": 0, "relogins": 0}
    samples: list[dict] = []
    fake_probe = lambda _path: SimpleNamespace(  # noqa: E731
        has_video=True, audio_streams=[], is_audio_only=False, duration=1.0)
    with tempfile.TemporaryDirectory(prefix="smoothcast-soak-") as scratch, \
            mock.patch.object(streamer, "ffprobe", fake_probe):
        upload_root = Path(scratch) / "uploads"
        harness = RoomHarness(count=QUEUE, uploads=portal_uploads.UploadManager(upload_root))
        try:
            server = harness.server
            server.clock = tick
            server.room.clock = tick
            big = (1e9, 1e9)
            server.request_limiter = portal_commands.ParticipantRateLimiter(
                clock=tick, limits={"read": big, "mutation": big, "upload": big})
            clients = [harness.login(f"Phone {i}") for i in range(PHONES)]
            ctx = SimpleNamespace(harness=harness, server=server, clients=clients, clock=clock, keep=[])

            def call(client_index: int, method: str, path: str, body=None, **extra):
                nonlocal clients
                for attempt in (0, 1):
                    client = clients[client_index]
                    status, data, _ = harness.request(method, path, body, cookie=client.cookie,
                                                      csrf=client.csrf, **extra)
                    if status in (401, 403) and attempt == 0:      # the phone's session expired: join again
                        clients[client_index] = harness.login(f"Phone {client_index}")
                        counts["relogins"] += 1
                        continue
                    return status, data
                return status, data

            for cycle in range(1, cycles + 1):
                clock.now += SECONDS_PER_CYCLE
                server.service_actions()
                for step in range(POLLS_PER_CYCLE):                # phones take turns polling
                    call((cycle * POLLS_PER_CYCLE + step) % PHONES, "GET", "/api/status")
                    counts["polls"] += 1
                _status, state = call(0, "GET", "/api/status")
                snapshot = state.get("state", {})
                queue, revision = snapshot.get("queue", []), snapshot.get("queue_revision", 0)
                for offset in range(4):                            # seeks from different phones
                    call((cycle + offset) % PHONES, "POST", "/api/action",
                         {"action": "seek", "value": float((cycle * 7 + offset) % 3000)})
                    counts["seeks"] += 1
                if queue:
                    voter = cycle % PHONES
                    call(voter, "POST", "/api/action", {"action": "queue_vote", "id": queue[0]["id"],
                                                        "value": cycle % 2 == 0})
                    counts["votes"] += 1
                    if cycle % 4 == 2:                             # one removal per upload keeps it ~500
                        call(voter, "POST", "/api/action", {
                            "action": "queue_remove", "id": queue[-1]["id"], "queue_revision": revision,
                            "queue_command_id": f"soak-rm-{cycle}"})
                        counts["queue_edits"] += 1
                    elif cycle % 4 == 1 and len(queue) > 2:
                        call(voter, "POST", "/api/action", {
                            "action": "queue_move", "id": queue[-1]["id"], "position": 0,
                            "queue_revision": revision, "queue_command_id": f"soak-mv-{cycle}"})
                        counts["queue_edits"] += 1
                if cycle % 4 == 0:                                 # a guest uploads a tiny file
                    uploader = cycle % PHONES
                    status, created = call(uploader, "POST", "/api/uploads",
                                           {"name": f"clip-{cycle}.mkv", "size": 6, "queue": True})
                    if status == 201:
                        call(uploader, "PUT", f"/api/uploads/{created['id']}", b"abcdef",
                             content_type="application/octet-stream",
                             extra_headers={"Content-Range": "bytes 0-5/6"})
                        call(uploader, "POST", f"/api/uploads/{created['id']}/complete", {"queue": True})
                        counts["uploads"] += 1
                guest = harness.login(f"Guest {cycle}")            # a visitor joins, looks, leaves
                harness.request("GET", "/api/status", cookie=guest.cookie)
                server.revoke_participant(guest.participant_id)
                counts["joins"] += 1
                for hook in hooks:
                    hook(cycle, ctx)
                if cycle % SAMPLE_EVERY == 0 or cycle == cycles:
                    samples.append(sample(cycle, harness, upload_root))
        finally:
            harness.close()
            for thread in threading.enumerate():
                if thread.name.startswith("soak-leak"):
                    getattr(thread, "release", lambda: None)()
    result = verdict(samples)
    result.update(counts=counts, cycles=cycles, simulated_hours=round(cycles * SECONDS_PER_CYCLE / 3600, 1),
                  series=samples)
    if report_path is not None:
        report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not quiet:
        print(table(result))
    return result


def table(result: dict) -> str:
    first, last = result["series"][0], result["series"][-1]
    lines = [f"soak: {result['cycles']} cycles (~{result['simulated_hours']} simulated hours), "
             f"{result['counts']['polls']} polls, {result['counts']['seeks']} seeks, "
             f"{result['counts']['joins']} joins, {result['counts']['uploads']} uploads, "
             f"{result['counts']['relogins']} re-logins",
             f"{'metric':<22}{'first sample':>14}{'last sample':>14}"]
    for name in ("threads", "fds", "rss_kb", "files"):
        lines.append(f"{name:<22}{first.get(name)!s:>14}{last.get(name)!s:>14}")
    for name in first["maps"]:
        lines.append(f"{'map:' + name:<22}{first['maps'][name]:>14}{last['maps'][name]:>14}")
    lines += [f"WARNING: {w}" for w in result["warnings"]] + [f"FAIL: {f}" for f in result["failures"]]
    lines.append(f"verdict: {result['verdict']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cycles", type=int, default=150)
    parser.add_argument("--report", type=Path, default=Path("soak-report.json"))
    args = parser.parse_args(argv)
    started = time.monotonic()
    result = run(args.cycles, report_path=args.report)
    print(f"{time.monotonic() - started:.0f} s; report: {args.report}")
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
