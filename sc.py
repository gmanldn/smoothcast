#!/usr/bin/env python3
"""Canonical SmoothCast launcher for Linux, macOS and Windows.

The same Python entry point prepares the project runtime, registers the Linux
desktop entry and starts the GTK application. `setup/launch.py` is the internal
GTK startup helper, not a second user-facing launcher.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SETUP = ROOT / "setup"


def _target() -> str | None:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def _headless(args: list[str]) -> bool:
    """Queries that must work before the runtime exists or while testing."""
    return (os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1"
            or "--self-test" in args
            or args in (["--version"], ["-V"])
            or args[:1] in (["--diagnostics"], ["--link-check"]))


def _bootstrap(target: str, *, portable: bool = False, in_place: bool = False) -> int:
    print("SmoothCast: preparing the project runtime", file=sys.stderr)
    return subprocess.call(
        [sys.executable, str(SETUP / "bootstrap.py"), "--target", target,
         *(["--in-place"] if portable or in_place else []),
         *(["--no-shortcuts"] if portable else [])],
    )


def _install_desktop(target: str) -> None:
    if target != "linux" or not (os.environ.get("DISPLAY")
                                 or os.environ.get("WAYLAND_DISPLAY")):
        return
    try:
        subprocess.call(
            [sys.executable, str(ROOT / "scripts" / "install_desktop.py"), "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass  # Desktop registration is best-effort and never blocks a launch.


def _installed_root(target: str) -> Path | None:
    """Use the installer's saved destination, or a recognisable OS default."""
    import install_location

    # A copy transaction can temporarily remove the bootstrap/manifest used
    # for discovery. Check the remembered path before interpreting that gap
    # as a missing installation.
    pointer = install_location.config_path(target)
    try:
        saved = Path(pointer.read_text(encoding="utf-8").strip()).expanduser()
        if saved.is_absolute():
            install_location.check_install_idle(saved)
    except FileNotFoundError:
        pass
    install_location.check_install_idle(install_location.default_directory(target))
    remembered = install_location.previous_directory(target)
    if remembered is not None:
        return remembered.resolve()
    default = install_location.default_directory(target)
    try:
        if ((default / "setup" / "bootstrap.py").is_file()
                and 'name = "smoothcast"' in (default / "pyproject.toml").read_text(encoding="utf-8")):
            return default.resolve()
    except (OSError, ValueError):
        pass
    return None


def _launch_installed(root: Path, args: list[str]) -> int:
    """Hand off once, preserving caller cwd, args and the installed runtime."""
    script = root / "sc.py"
    if not script.is_file():
        # Older registered installations predate sc.py.
        script = root / "setup" / "launch.py"
    if not script.is_file():
        print(f"SmoothCast installation at {root} is incomplete; rerun setup.", file=sys.stderr)
        return 1
    print(f"SmoothCast: using installed application at {root}", file=sys.stderr, flush=True)
    try:
        return subprocess.call([sys.executable, str(script), *args])
    except OSError as exc:
        print(f"SmoothCast could not start installed application: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if sys.version_info < (3, 10):
        print("SmoothCast needs Python 3.10+; run the platform setup script first.",
              file=sys.stderr)
        return 1

    # Demo runs the app against loopback-only fake receivers in a throwaway
    # profile. Handle it before any installed-copy redirect, single-instance
    # handoff or runtime install so it can never touch a real running SmoothCast.
    if any(arg == "--demo" or arg.startswith("--demo=") for arg in args):
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(SETUP))
        import demo_launch
        if args != ["--demo"]:
            return demo_launch.run(args)
        import launch
        if not launch.runtime_ready():
            print("Demo mode needs the SmoothCast runtime; run SmoothCast once to set it up.",
                  file=sys.stderr)
            return 1
        try:
            return demo_launch.run(args, str(launch.python_path()), launch.runtime_environment())
        except (OSError, RuntimeError) as exc:
            print(f"SmoothCast demo could not start: {exc}", file=sys.stderr)
            return 1

    portable = args[:1] == ["--portable"]
    if portable:
        args = args[1:]
    sys.path.insert(0, str(SETUP))
    import launch

    # Tests must remain isolated even when a real installation exists.
    if "--self-test" in args or os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        return launch.main(args)

    target = _target()
    installed = None
    try:
        import install_location

        install_location.check_install_idle(ROOT)
        if target is not None and not portable:
            installed = _installed_root(target)
    except (OSError, ValueError) as exc:
        print(f"SmoothCast: installation unavailable: {exc}", file=sys.stderr)
        return 1
    if target is not None and not portable:
        if installed is not None and installed != ROOT.resolve():
            if not _headless(args):
                import checkout_refresh

                code = checkout_refresh.refresh(
                    ROOT, installed, target,
                    lambda: launch.gui_instances(all_installations=True),
                )
                if code:
                    return code
            return _launch_installed(installed, args)
    if _headless(args):
        return launch.main(args)

    if target is None:
        print("SmoothCast supports Linux, macOS and Windows 10/11 x64.", file=sys.stderr)
        return 1
    # Activating the already-running primary must not wait for dependency
    # probes, bootstrap, installs or desktop registration (#540).
    guarded = launch.ensure_single_instance(args)
    if guarded is not None:
        return guarded
    if not launch.runtime_ready():
        if portable:
            code = _bootstrap(target, portable=True)
        elif installed == ROOT.resolve():
            code = _bootstrap(target, in_place=True)
        else:
            code = _bootstrap(target)
        if code:
            return code
        if not portable:
            # Setup normally copies to a per-user install, not this checkout.
            try:
                installed = _installed_root(target)
            except (OSError, ValueError) as exc:
                print(f"SmoothCast: installation unavailable: {exc}", file=sys.stderr)
                return 1
            if installed is not None and installed != ROOT.resolve():
                return _launch_installed(installed, args)
        if not launch.runtime_ready():
            print("SmoothCast setup finished but no usable runtime was found. "
                  "Rerun the platform setup script to repair the installation.", file=sys.stderr)
            return 1
    if not portable:
        _install_desktop(target)
    # Direct installed shortcuts and portable starts also identify the actual
    # selected runtime. Do not describe a checkout as remotely up to date.
    import checkout_refresh

    version = checkout_refresh.read_version(ROOT)
    if version is not None:
        checkout_refresh.announce(
            version, checkout_refresh.installed_revision(ROOT), "Loading selected runtime version",
        )
    return launch.main(args, prechecked=True)


if __name__ == "__main__":
    raise SystemExit(main())
