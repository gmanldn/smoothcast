"""Tiny GTK-free entry point for installed SmoothCast commands."""
from __future__ import annotations

import os
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
    if sys.argv[1:2] == ["--network-check"]:
        # Explicit diagnostic command; does not import GTK or start a cast.
        import network_routes
        return network_routes.main(sys.argv[2:])
    if sys.argv[1:2] and sys.argv[1] in ("cast", "pause", "resume", "stop", "seek", "status"):
        # Headless Chromecast control (#268): never imports GTK or opens a window.
        import cli_control
        return cli_control.main(sys.argv[1:])
    if sys.argv[1:2] == ["--control-api"]:
        # Opt-in headless HTTP control (#269); never imports GTK.
        import control_api
        return control_api.main(sys.argv[2:])
    if sys.argv[1:2] == ["--reprobe-encoder"]:
        # Explicit, headless: forget a recorded VAAPI failure (#236).
        import hw_encoder_state
        return hw_encoder_state.main(sys.argv[2:])
    if sys.argv[1:2] == ["--library-index"]:
        # Explicit, headless scan/list; never loads GTK or touches a receiver.
        import library_index
        return library_index.main(sys.argv[2:])
    if os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        print("Refusing to start GTK from pytest; only portable tests run there.", file=sys.stderr)
        return 2
    # Reject unsafe self-tests *before importing GTK* or connecting to a
    # developer's running GApplication (which would steal desktop focus).
    if "--self-test" in sys.argv[1:]:
        from gui_test_safety import is_isolated_gui_test, refusal
        if not is_isolated_gui_test():
            print(refusal(), file=sys.stderr)
            return 2
    # Import native GUI dependencies only when actually starting the app.
    from cast_control import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
