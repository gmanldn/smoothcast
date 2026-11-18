"""Tiny GTK-free entry point for installed SmoothCast commands."""
from __future__ import annotations

import sys


def main() -> int:
    if sys.argv[1:] in (["--version"], ["-V"]):
        from version import label
        print(f"SmoothCast {label()}")
        return 0
    # Import native GUI dependencies only when actually starting the app.
    from cast_control import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
