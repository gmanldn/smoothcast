"""Tiny GTK-free entry point for installed SmoothCast commands."""
from __future__ import annotations

import os
import sys


def main() -> int:
    from frozen_runtime import dispatch_frozen_helper, is_frozen
    child = dispatch_frozen_helper(sys.argv[1:])
    if child is not None:
        return child
    if sys.argv[1:] == ["--_smoothcast-package-check"]:
        if not is_frozen():
            print("Package integrity check is for frozen artefacts only.", file=sys.stderr)
            return 2
        import hashlib
        import gi
        from smoothcast_assets import icon_path
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        # Import the GI namespaces to validate native packaging without a display.
        from gi.repository import Gtk, Adw  # noqa: F401
        print(hashlib.sha256(icon_path().read_bytes()).hexdigest())
        return 0
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
