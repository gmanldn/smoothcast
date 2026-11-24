"""Write or verify the Windows payload manifest. Static checks only; nothing is launched (#528).

    python scripts/ci/verify_windows_payload.py --dist dist/SmoothCast --write-manifest
    python scripts/ci/verify_windows_payload.py --dist dist/SmoothCast
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import windows_payload  # noqa: E402
import version  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--write-manifest", action="store_true",
                        help="record the payload first (the build step), then verify it")
    args = parser.parse_args(argv)
    if not args.dist.is_dir():
        print(f"{args.dist} is not a directory", file=sys.stderr)
        return 2
    if args.write_manifest:
        try:
            windows_payload.write_manifest(args.dist, version.__version__)
        except windows_payload.PayloadError as exc:
            print(f"cannot describe the payload: {exc}", file=sys.stderr)
            return 1
    problems = windows_payload.verify(args.dist, version.__version__)
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if not problems:
        print(f"Windows payload OK ({args.dist})")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
