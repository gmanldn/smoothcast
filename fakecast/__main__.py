"""Run the development CASTV2 receiver fake."""

from __future__ import annotations

import argparse
import sys
import time

from .profiles import PROFILES
from .receiver import FakeCastReceiver


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a loopback CASTV2 fake receiver")
    parser.add_argument("--port", type=int, default=8009)
    parser.add_argument("--profile", choices=tuple(PROFILES), default="generic")
    args = parser.parse_args()
    try:
        with FakeCastReceiver(port=args.port, profile=args.profile, advertise=True) as receiver:
            print(f"Fake Cast receiver listening on {receiver.host}:{receiver.port}", flush=True)
            if receiver.advertisement_active:
                print(f"Advertised as {receiver.service_name}", flush=True)
            elif receiver.advertising_error:
                print(f"mDNS unavailable: {receiver.advertising_error}", file=sys.stderr, flush=True)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
