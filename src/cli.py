"""Tiny GTK-free entry point for installed SmoothCast commands."""
from __future__ import annotations

import sys


def main() -> int:
    if sys.argv[1:] in (["--version"], ["-V"]):
        from version import label
        print(f"SmoothCast {label()}")
        return 0
    if sys.argv[1:2] == ["--diagnostics"]:
        # Bounded, redacted support bundle; never needs GTK or a display.
        import diagnostics
        return diagnostics.main(sys.argv[2:])
    # Import native GUI dependencies only when actually starting the app.
    from cast_control import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
