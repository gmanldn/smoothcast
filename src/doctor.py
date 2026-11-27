"""`smoothcast doctor` core (#211): read-only checks with PASS/WARN/FAIL and remediation.

Every check is a small function over injectable probes so it is testable without
a network, GTK or FFmpeg. Nothing here changes the system; fixes are only ever
*described* (``fix`` text), never applied.
"""
from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

PASS, WARN, FAIL = "pass", "warn", "fail"
MIN_FREE_BYTES = 2 * 1024 ** 3
CAST_PORT = 8009
REQUIRED_FILTERS = ("subtitles", "overlay", "acompressor", "alimiter", "loudnorm")
MIN_SANE_EPOCH = 1_700_000_000   # Nov 2023: a clock before this is certainly wrong


@dataclass(frozen=True)
class Result:
    name: str
    status: str
    detail: str
    fix: str = ""


def python_version(version: tuple = tuple(sys.version_info[:3])) -> Result:
    if version >= (3, 10):
        return Result("python", PASS, "Python %d.%d.%d" % tuple(version[:3]))
    return Result("python", FAIL, "Python %d.%d is too old" % tuple(version[:2]),
                  "Install Python 3.10 or newer.")


def ffmpeg(which: Callable[[str], str | None] = shutil.which,
           filters: Callable[[], set[str]] | None = None) -> Result:
    missing_tools = [t for t in ("ffmpeg", "ffprobe") if not which(t)]
    if missing_tools:
        return Result("ffmpeg", FAIL, "Missing: " + ", ".join(missing_tools),
                      "Install FFmpeg with your package manager.")
    have = filters() if filters else None
    if have is None:
        return Result("ffmpeg", WARN, "FFmpeg found; filters were not checked")
    lacking = [f for f in REQUIRED_FILTERS if f not in have]
    if lacking:
        return Result("ffmpeg", WARN, "FFmpeg lacks: " + ", ".join(lacking),
                      "Install a full FFmpeg build (subtitles needs libass).")
    return Result("ffmpeg", PASS, "FFmpeg and all required filters present")


def receiver(host: str, port: int = CAST_PORT, timeout: float = 2.0,
             connect: Callable = socket.create_connection) -> Result:
    try:
        connect((host, port), timeout).close()
    except OSError as exc:
        return Result("receiver", FAIL, f"Cannot reach {host}:{port} ({exc.__class__.__name__})",
                      "Check the TV is on, on the same network, and that a firewall or VPN is not blocking port 8009.")
    return Result("receiver", PASS, f"{host}:{port} accepts connections")


def disk_space(path: str | Path, usage: Callable = shutil.disk_usage) -> Result:
    try:
        free = usage(path).free
    except OSError as exc:
        return Result("disk", FAIL, f"Cannot read free space ({exc.__class__.__name__})")
    if free < MIN_FREE_BYTES:
        return Result("disk", WARN, f"Only {free // 1024 ** 2} MiB free",
                      "Free about 2 GiB for transcoding and remux.")
    return Result("disk", PASS, f"{free // 1024 ** 3} GiB free")


def temp_writable(tmp: Callable = tempfile.TemporaryFile) -> Result:
    try:
        with tmp():
            pass
    except OSError as exc:
        return Result("tempdir", FAIL, f"Temp directory is not writable ({exc.__class__.__name__})",
                      "Fix permissions on your temp directory or set TMPDIR.")
    return Result("tempdir", PASS, "Temp directory is writable")


def listener(bind: Callable = socket.socket) -> Result:
    try:
        with bind(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
    except OSError as exc:
        return Result("listener", FAIL, f"Cannot open a local server socket ({exc.__class__.__name__})",
                      "Check for a security tool blocking local servers.")
    return Result("listener", PASS, "Local server socket can be opened")


def multicast(bind: Callable = socket.socket) -> Result:
    """Can this host join the SSDP multicast group (DLNA/Cast discovery)? No packets are sent."""
    import struct

    try:
        with bind(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            struct.pack("4s4s", socket.inet_aton("239.255.255.250"),
                                        socket.inet_aton("0.0.0.0")))
    except OSError as exc:
        return Result("multicast", WARN,
                      f"Cannot join the discovery multicast group ({exc.__class__.__name__})",
                      "Check the network has a default route and that a VPN or firewall allows "
                      "multicast; you can still add a receiver by IP.")
    return Result("multicast", PASS, "Discovery multicast group can be joined")


def default_route(connect: Callable = socket.socket) -> Result:
    """Is there a LAN route out? UDP connect sends nothing; it only selects an interface."""
    try:
        with connect(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            address = sock.getsockname()[0]
    except OSError as exc:
        return Result("network", FAIL, f"No usable network route ({exc.__class__.__name__})",
                      "Connect to the same Wi-Fi or Ethernet network as your TV.")
    if address.startswith("127."):
        return Result("network", FAIL, "Only a loopback address is available",
                      "Connect to the same Wi-Fi or Ethernet network as your TV.")
    return Result("network", PASS, f"Network route found via {address}")


def clock(now: Callable[[], float] = time.time) -> Result:
    if now() < MIN_SANE_EPOCH:
        return Result("clock", WARN, "System clock looks wrong", "Enable automatic time sync.")
    return Result("clock", PASS, "System clock looks sane")


def run(checks: list[Callable[[], Result]]) -> list[Result]:
    """Run every check; a crashing check becomes a FAIL, never a crash."""
    out: list[Result] = []
    for check in checks:
        try:
            out.append(check())
        except Exception as exc:  # noqa: BLE001 - the doctor must always finish
            out.append(Result(getattr(check, "__name__", "check"), FAIL,
                              f"Check crashed: {exc.__class__.__name__}"))
    return out


def overall(results: list[Result]) -> str:
    return FAIL if any(r.status == FAIL for r in results) else WARN if any(r.status == WARN for r in results) else PASS


def to_json(results: list[Result]) -> str:
    return json.dumps({"status": overall(results), "checks": [asdict(r) for r in results]}, indent=2)


def exit_code(results: list[Result]) -> int:
    return {PASS: 0, WARN: 1, FAIL: 2}[overall(results)]


def main(argv: list[str] | None = None) -> int:
    """``smoothcast doctor [--json] [--receiver HOST]``: read-only, headless."""
    import argparse

    parser = argparse.ArgumentParser(prog="smoothcast doctor",
                                     description="Read-only environment checks with remediation.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--receiver", metavar="HOST", help="also check this receiver is reachable")
    args = parser.parse_args(argv)
    cache = Path.home() / ".cache" / "cast-control"
    checks: list[Callable[[], Result]] = [
        python_version, ffmpeg, lambda: disk_space(cache), temp_writable, listener,
        default_route, multicast, clock]
    if args.receiver:
        checks.append(lambda: receiver(args.receiver))
    results = run(checks)
    if args.json:
        print(to_json(results))
    else:
        mark = {PASS: "ok  ", WARN: "warn", FAIL: "FAIL"}
        for r in results:
            print(f"[{mark.get(r.status, r.status)}] {r.name}: {r.detail}")
            if r.fix and r.status != PASS:
                print(f"       fix: {r.fix}")
        print(f"overall: {overall(results)}")
    return exit_code(results)
