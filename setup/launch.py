"""Portable SmoothCast launcher using the environment created by setup/bootstrap.py.

This module never installs anything or mutates dependency state. It is safe as
the target of native desktop shortcuts and can diagnose incomplete installs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import bootstrap
import native_runtime

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
RUNTIME_CHECK = bootstrap.GUI_CHECK + "; " + bootstrap.CAST_DEPENDENCIES_CHECK


def runtime_python() -> Path | None:
    candidates = (
        VENV / "bin" / "python",
        VENV / "Scripts" / "python.exe",
        VENV / "bin" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def python_path() -> Path:
    candidate = runtime_python()
    if candidate is None:
        raise FileNotFoundError(
            f"SmoothCast is not installed under {VENV}. Run the setup script first."
        )
    return candidate


def runtime_ready() -> bool:
    """True when the project runtime and media tools can start without setup."""
    runtime = runtime_python()
    if runtime is None:
        return False
    try:
        result = subprocess.run(
            [str(runtime), "-c", RUNTIME_CHECK],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    try:
        path = runtime_environment().get("PATH")
    except (OSError, RuntimeError):
        path = os.environ.get("PATH")
    return all(shutil.which(tool, path=path) for tool in ("ffmpeg", "ffprobe", "ffplay"))


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


# Recognise real URI arguments without mistaking Windows C:\\ paths for schemes.
# The launcher must never turn a web/mesh source into a local checkout path.
_URI_ARGUMENT = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:(?://|[?])")


def media_arguments_from_caller(args: list[str], caller: Path) -> list[str]:
    """Resolve film arguments before switching cwd to the installed checkout.

    Preserve URIs (https://, magnet:?xt=..., file://), flags and --action
    values. A missing relative filename must
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
        elif argument.startswith("-") or _URI_ARGUMENT.match(argument):
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
# primary that cannot build its window (or that has hung) may keep the app id
# while forwarding later launches to no visible window. Probe the primary;
# a failed activation MUST NOT kill a process by unverified PID or start a
# second competing GUI. The user can resolve a truly hung instance explicitly.

def app_identity() -> tuple[str, str]:
    """Read the application id and D-Bus object path without importing GTK."""
    source = (ROOT / "src" / "cast_widgets.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_ID\s*=\s*"([^"]+)"', source, re.MULTILINE)
    app_id = match.group(1) if match else "local.cast-control"
    # GApplication maps dots to path separators and dashes to underscores.
    return app_id, "/" + app_id.replace("-", "_").replace(".", "/")


# Interpreter switches which do not consume a following value. Never skip
# -c, -m, -X, -W or arbitrary options: their operands are not a script path.
_PYTHON_NO_VALUE_SWITCHES = frozenset({
    "-B", "-E", "-I", "-O", "-OO", "-P", "-s", "-S", "-u",
})


def is_gui_python_command(argv: list[str], target: str) -> bool:
    """True only if Python executes target as its actual script argument.

    Bounded parsing avoids treating an arbitrary later file operand as our app.
    Unknown flags and -c/-m invocations deliberately fail closed; -W/-X\n    option values are consumed before identifying the real script operand.
    """
    if len(argv) < 2 or not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)?)?(?:[a-z])?", Path(argv[0]).name):
        return False
    index = 1
    while index < len(argv):
        option = argv[index]
        if option in _PYTHON_NO_VALUE_SWITCHES:
            index += 1
        elif option in ("-W", "-X"):
            # Python consumes exactly one value after these switches.
            # Never mistake that value for the application's script path.
            if (index + 1 >= len(argv) or not argv[index + 1]
                    or argv[index + 1].startswith("-")):
                return False
            index += 2
        elif (option.startswith("-W") or option.startswith("-X")) and len(option) > 2:
            index += 1
        else:
            break
    return index < len(argv) and argv[index] == target


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
        if is_gui_python_command(argv, target):
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


def ensure_single_instance(args: list[str]) -> int | None:
    """Exit code to stop launching, or None to start a new instance."""
    if os.name != "posix":
        return None
    pids = gui_instances()
    if not pids:
        return None
    activated = activate_existing()
    if activated:
        if not args:
            # Existing primary confirmed its activation; no extra GUI.
            return 0
        # Forward file and action arguments through GApplication.
        return None
    # A D-Bus timeout or missing probe is NOT proof of a hung process. In
    # particular, a PID found in /proc may be reused before SIGTERM/SIGKILL.
    # Preserve a possibly active cast and refuse to create a competing GUI.
    print(
        "SmoothCast is already running but its window could not be activated. "
        "The existing process was left untouched. Close it normally (or use "
        "your system process manager if it is unresponsive), then retry.",
        file=sys.stderr,
    )
    return 3


def main(argv: list[str] | None = None, *, prechecked: bool = False) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Direct shortcut/launcher calls must not bypass demo isolation (#523).
    if any(arg == "--demo" or arg.startswith("--demo=") for arg in args):
        print("Demo mode is not ready. No receiver was contacted.", file=sys.stderr)
        return 2
    if args in (["--version"], ["-V"]):
        return subprocess.call([sys.executable, str(ROOT / "src" / "version.py")])
    if args[:1] == ["--link-check"]:
        # Use the recorded native runtime PATH, but never start the application.
        try:
            env = runtime_environment()
        except (OSError, RuntimeError) as exc:
            print(f"SmoothCast native runtime unavailable: {exc}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(ROOT / "src" / "link_acquisition.py"),
                                *args[1:]], env=env)
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
    # Always activate/diagnose the existing primary BEFORE checking the venv.
    # Its environment may have been moved during an update, while it remains
    # healthy and able to forward the caller's request.
    if not prechecked:
        guarded = ensure_single_instance(args)
        if guarded is not None:
            return guarded
    try:
        installed = python_path()
    except FileNotFoundError as exc:
        print(f"SmoothCast: {exc}", file=sys.stderr)
        return 1
    # GTK's process cwd is intentionally ROOT; preserve the caller's media
    # paths before os.chdir/Windows subprocess cwd changes that reference.
    media_args = media_arguments_from_caller(args, Path.cwd())
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
