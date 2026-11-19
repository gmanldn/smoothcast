"""Portable SmoothCast launcher using the environment created by setup/bootstrap.py.

This module never installs anything or mutates dependency state. It is safe as
the target of native desktop shortcuts and can diagnose incomplete installs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

import native_runtime

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def python_path() -> Path:
    candidates = (
        VENV / "bin" / "python",
        VENV / "Scripts" / "python.exe",
        VENV / "bin" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"SmoothCast is not installed under {VENV}. Run the setup script first."
    )


def _runtime_environment_for(target: str, initial: dict[str, str]) -> dict[str, str]:
    """Construct a launch environment from the *installed* native GTK prefix."""
    env = dict(initial)
    record = native_runtime.load(VENV, target=target)
    if record is not None:
        native_python = Path(str(record["native_python"]))
        if not native_python.is_file():
            raise RuntimeError(
                f"Selected native Python moved or is missing: {native_python}. "
                "Rerun the platform setup script; another runtime will not be substituted."
            )
    if target == "windows":
        root = (Path(str(record["prefix"])) if record else
                Path(initial.get("MSYS2_ROOT") or
                     initial.get("SystemDrive", "C:") + "\\msys64"))
        ucrt = root / "ucrt64"
        if record and not (ucrt / "bin" / "python.exe").is_file():
            raise RuntimeError(
                f"Selected MSYS2 runtime moved: {root}. Rerun Windows setup."
            )
        env["MSYS2_ROOT"] = str(root)
        env["PATH"] = os.pathsep.join(
            (str(ucrt / "bin"), str(root / "usr" / "bin"), env.get("PATH", "")),
        )
        env["PYGI_DLL_PATH"] = str(ucrt / "bin")
        env["GI_TYPELIB_PATH"] = str(ucrt / "lib" / "girepository-1.0")
        env["XDG_DATA_DIRS"] = os.pathsep.join(
            (str(ucrt / "share"), env.get("XDG_DATA_DIRS", "")),
        )
    elif target == "macos":
        if record:
            prefix = Path(str(record["prefix"]))
            if not (prefix / "bin" / "brew").is_file():
                raise RuntimeError(
                    f"Selected Homebrew prefix moved: {prefix}. Rerun macOS setup."
                )
        else:
            prefixes = (Path("/opt/homebrew"), Path("/usr/local"))
            installed = [p for p in prefixes if (p / "bin" / "brew").exists()]
            prefix = installed[0] if installed else None
        if prefix is not None:
            env["SMOOTHCAST_NATIVE_PREFIX"] = str(prefix)
            env["PATH"] = os.pathsep.join(
                (str(prefix / "bin"), str(prefix / "sbin"), env.get("PATH", "")),
            )
            typelib = prefix / "lib" / "girepository-1.0"
            if typelib.is_dir():
                env["GI_TYPELIB_PATH"] = os.pathsep.join(
                    (str(typelib), env.get("GI_TYPELIB_PATH", "")),
                )
    return env


def runtime_environment() -> dict[str, str]:
    target = "windows" if os.name == "nt" else (
        "macos" if sys.platform == "darwin" else "linux"
    )
    return _runtime_environment_for(target, dict(os.environ))


def media_arguments_from_caller(args: list[str], caller: Path) -> list[str]:
    """Resolve film arguments before switching cwd to the installed checkout.

    Ignore URLs, flags and --action values. A missing relative filename must
    also become caller-absolute, otherwise a same-named checkout file could
    be silently opened instead. No filesystem mutation or GTK interaction.
    """
    result: list[str] = []
    action_value = False
    for argument in args:
        if action_value:
            result.append(argument)
            action_value = False
        elif argument == "--action":
            result.append(argument)
            action_value = True
        elif argument.startswith("-") or argument.startswith("file://"):
            result.append(argument)
        else:
            try:
                candidate = Path(argument).expanduser()
                if not candidate.is_absolute():
                    candidate = caller / candidate
                result.append(str(candidate.resolve()))
            except (OSError, RuntimeError, ValueError):
                result.append(argument)
    return result


# --- Single instance guard --------------------------------------------------
#
# GApplication already forwards a launch to a running primary over D-Bus, but a
# primary that cannot build its window (or that has hung) keeps the application
# id with nothing on screen: further launches forward to it and show nothing.
# Before starting a new instance, ask any same-checkout instance to present
# itself; when it cannot, clear it out so this launch always ends with a window.

def app_identity() -> tuple[str, str]:
    """Read the application id and D-Bus object path without importing GTK."""
    source = (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_ID\s*=\s*"([^"]+)"', source, re.MULTILINE)
    app_id = match.group(1) if match else "local.cast-control"
    # GApplication maps dots to path separators and dashes to underscores.
    return app_id, "/" + app_id.replace("-", "_").replace(".", "/")


def gui_instances(proc_root: Path = Path("/proc"),
                  exclude: set[int] | None = None) -> list[int]:
    """PIDs of other same-user processes running *this* checkout's GTK app."""
    target = str((ROOT / "src" / "cast_control.py").resolve())
    skip = {os.getpid(), os.getppid()} | (exclude or set())
    found: list[int] = []
    try:
        entries = [entry for entry in proc_root.iterdir() if entry.name.isdecimal()]
    except OSError:
        return found
    for entry in entries:
        if int(entry.name) in skip:
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            argv = [part.decode("utf-8", "replace")
                    for part in (entry / "cmdline").read_bytes().split(b"\0") if part]
        except OSError:
            continue
        if len(argv) >= 2 and target in argv[1:] \
                and Path(argv[0]).name.startswith("python"):
            found.append(int(entry.name))
    return found


def activate_existing(timeout: float = 6.0) -> bool | None:
    """Ask the running instance to show its window.

    True when it accepted (window raised), False when it refused or timed out,
    and None when the running instance cannot be probed safely.
    """
    app_id, object_path = app_identity()
    if shutil.which("gdbus") is None:
        return None
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") and \
            not Path(f"/run/user/{os.getuid()}/bus").exists():
        return None
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session", "--dest", app_id,
             "--object-path", object_path,
             "--method", "org.gtk.Application.Activate", "{}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_instances(pids: list[int], grace: float = 3.0) -> list[int]:
    """Terminate leftover instances gracefully, then forcibly."""
    signalled = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
        signalled.append(pid)
    pending = [pid for pid in signalled if _alive(pid)]
    deadline = time.monotonic() + max(0.0, grace)
    while pending and time.monotonic() < deadline:
        pending = [pid for pid in pending if _alive(pid)]
        if pending:
            time.sleep(0.05)
    for pid in pending:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return signalled


def ensure_single_instance(args: list[str]) -> int | None:
    """Exit code to stop launching, or None to start a new instance."""
    if os.name != "posix":
        return None
    pids = gui_instances()
    if not pids:
        return None
    activated = activate_existing()
    if activated is None:
        # Cannot probe: leave single-instance handling to GApplication.
        return None
    if activated:
        if not args:
            # The existing window is showing and there is nothing to open, so a
            # second process would only add another windowless client.
            return 0
        # Media arguments still have to be forwarded, so let GApplication do it.
        return None
    stopped = stop_instances(pids)
    print("SmoothCast: cleared " + str(len(stopped)) + " unresponsive instance(s)",
          file=sys.stderr)
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        return subprocess.call([sys.executable, str(ROOT / "src" / "version.py")])
    if args[:1] == ["--diagnostics"]:
        # GTK-free support bundle: works even when the runtime is broken.
        return subprocess.call(
            [sys.executable, str(ROOT / "src" / "diagnostics.py"), *args[1:]],
        )
    # Native desktop shortcuts and direct launcher calls are not GUI test
    # harnesses. Refuse before starting another GTK process.
    if "--self-test" in args or os.environ.get("SMOOTHCAST_TEST_CONTEXT") == "1":
        print("Refusing GUI startup during testing; use "
              "python3 scripts/test_gui_isolated.py for opt-in Xvfb smoke.",
              file=sys.stderr)
        return 2
    try:
        installed = python_path()
    except FileNotFoundError as exc:
        print(f"SmoothCast: {exc}", file=sys.stderr)
        return 1
    # GTK's process cwd is intentionally ROOT; preserve the caller's media
    # paths before os.chdir/Windows subprocess cwd changes that reference.
    media_args = media_arguments_from_caller(args, Path.cwd())
    guarded = ensure_single_instance(args)
    if guarded is not None:
        return guarded
    command = [str(installed), str(ROOT / "src" / "cast_control.py"), *media_args]
    try:
        env = runtime_environment()
        if os.name != "nt":
            # A .desktop launch may inherit HOME or / as its working directory.
            # Use the same project root as the Windows launcher.
            os.chdir(ROOT)
            os.execvpe(command[0], command, env)
        return subprocess.call(command, cwd=ROOT, env=env)
    except (OSError, RuntimeError) as exc:
        print(f"SmoothCast could not start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
