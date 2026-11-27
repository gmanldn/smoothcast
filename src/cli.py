"""Tiny GTK-free entry point for installed SmoothCast commands."""
from __future__ import annotations

import os
import sys


def main() -> int:
    """Run the command; an unexpected error becomes one civil line, never a traceback."""
    try:
        return _main()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # SystemExit (argparse, explicit exits) passes through
        import failure_boundary
        failure = failure_boundary.describe(exc)
        logged = False
        try:
            import error_log
            error_log.log(f"cli failed: {failure.detail}")
            logged = True
        except Exception:
            pass
        print(f"smoothcast: {failure.message}", file=sys.stderr)
        if logged:
            print("Details were written to the private error log.", file=sys.stderr)
        return 1


def _main() -> int:
    # Before frozen helper dispatch or GTK imports: demo runs in a throwaway
    # loopback-only profile and never touches the user's SmoothCast (#523).
    if any(arg == "--demo" or arg.startswith("--demo=") for arg in sys.argv[1:]):
        import demo_launch
        return demo_launch.run(sys.argv[1:])
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
    if sys.argv[1:] == ["--_smoothcast-media-probe"]:
        # Headless: `<tool> -version` only; never media, GTK or a receiver (#530).
        import json
        import media_tools
        result = media_tools.report()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if sys.argv[1:] == ["--build-id"]:
        # Read the checkout revision once at command invocation. A packaged
        # build without .git reports only the embedded semantic baseline.
        from pathlib import Path
        from version import build_label, read_checkout_revision
        source_root = Path(__file__).resolve().parents[1]
        print(f"SmoothCast {build_label(read_checkout_revision(source_root))}")
        return 0
    if sys.argv[1:] in (["--version"], ["-V"]):
        from version import label
        print(f"SmoothCast {label()}")
        return 0
    if sys.argv[1:2] == ["--diagnostics"]:
        # Bounded, redacted support bundle; never needs GTK or a display.
        import diagnostics
        return diagnostics.main(sys.argv[2:])
    if sys.argv[1:2] == ["--forget-receiver"]:
        # Explicit, local-only privacy reset. No GI, display or receiver activity.
        import receiver_memory
        return receiver_memory.main(sys.argv[2:])
    if sys.argv[1:2] == ["--link-check"]:
        # Explicit read-only engine checks; no GTK, receiver or source requests.
        import link_acquisition
        return link_acquisition.diagnostics_main(sys.argv[2:])
    if sys.argv[1:2] == ["--network-check"]:
        # Explicit diagnostic command; does not import GTK or start a cast.
        import network_routes
        return network_routes.main(sys.argv[2:])
    if sys.argv[1:2] and sys.argv[1] in ("cast", "pause", "resume", "stop", "seek", "status"):
        # Headless Chromecast control (#268): never imports GTK or opens a window.
        import cli_control
        return cli_control.main(sys.argv[1:])
    if sys.argv[1:2] == ["import"]:
        # Jellyfin/Plex/Kodi watch-state import, dry run by default (#435); no GTK.
        import importers
        return importers.main(sys.argv[2:])
    if sys.argv[1:2] == ["export"]:
        # Plain-file export of queue/history/rooms/preferences (#435); no GTK.
        import exporters
        return exporters.main(sys.argv[2:])
    if sys.argv[1:2] == ["house"]:
        # Room HTTP API client (#434); headless, never imports GTK.
        import house_cli
        return house_cli.main(sys.argv[2:])
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
