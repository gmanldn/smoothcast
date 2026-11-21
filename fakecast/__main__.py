"""Run the development CASTV2 receiver fake."""

from __future__ import annotations

import argparse
import time

from .receiver import FakeCastReceiver


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a loopback CASTV2 fake receiver")
    parser.add_argument("--port", type=int, default=8009)
    parser.add_argument("--profile", choices=("generic",), default="generic")
    args = parser.parse_args()
    try:
        with FakeCastReceiver(port=args.port, profile=args.profile) as receiver:
            print(f"Fake Cast receiver listening on {receiver.host}:{receiver.port}", flush=True)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
