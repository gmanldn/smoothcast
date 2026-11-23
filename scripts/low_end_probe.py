"""Optional, reproducible two-core software encoder test (no GUI or receiver).

Linux:
    python3 scripts/low_end_probe.py --cpus 0,1 --output /tmp/smoothcast-low-end.json

The output is informational; CI must not mistake a hosted runner for the
physical 10-year-old reference machine. No user films or network are touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
import low_end_policy as low  # noqa: E402


def measure(cpus: str = "0,1", *, runner=None, which=None) -> dict[str, object]:
    if not re.fullmatch(r"[0-9]+(?:[-,][0-9]+)*", cpus):
        raise ValueError("CPU affinity must be numeric, such as 0,1 or 0-1")
    lookup = shutil.which if which is None else which
    for executable in ("taskset", "nice", "ffmpeg"):
        if not lookup(executable):
            raise OSError(f"{executable} is required for a throttled Linux benchmark")
    run = subprocess.run if runner is None else runner

    def throttled(argv, **kwargs):
        return run(["taskset", "-c", cpus, "nice", "-n", "10", *argv], **kwargs)

    started = time.monotonic()
    fps = benchmark.run_probe(seconds=4, height=1080, runner=throttled)
    result = {
        "scenario": low.budget(),
        "affinity": cpus,
        "preset": "veryfast",
        "measured_fps": fps,
        "measured_speed_x": round(fps / 30, 3) if fps is not None else None,
        "recommended_tier": low.choose_tier(fps, type("Video", (), {"fps": 30.0})()),
        "probe_wall_seconds": round(time.monotonic() - started, 2),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cpus", default="0,1", help="allowed affinity CPUs, e.g. 0,1")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    args = parser.parse_args(argv)
    try:
        result = measure(args.cpus)
        text = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0 if result["measured_fps"] is not None else 1
    except (OSError, ValueError) as exc:
        print(f"low-end probe failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
