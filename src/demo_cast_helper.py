"""Demo-mode stand-in for the ``catt cast`` subprocess (#524).

The streamer launches a separate ``catt`` process to load media. In demo mode
that process must reach only the profile's loopback fake receiver, so this
helper runs the same ``-d NAME cast ...`` arguments through the demo backend.
Refuses to run unless demo mode is active (fail closed).
"""
from __future__ import annotations

import sys
import time


def main(argv: list[str]) -> int:
    import demo_mode
    if not demo_mode.active():
        print("demo cast helper needs demo mode", file=sys.stderr)
        return 2
    if len(argv) < 3 or argv[0] != "-d":
        print("usage: -d DEVICE COMMAND ...", file=sys.stderr)
        return 2
    import castctl
    castctl.scan(timeout=8)
    # A fresh process scans and commands at once; the socket needs a moment.
    deadline = time.monotonic() + 8
    while True:
        ok, message = castctl.command(argv[1], *argv[2:], timeout=20)
        if ok or time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    if not ok:
        print(message or "demo receiver refused the command", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
