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
import tempfile

import bootstrap
import managed_startup
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
    managed = managed_target()
    if managed is not None:
        return managed[0]
    candidate = runtime_python()
    if candidate is None:
        raise FileNotFoundError(
            f"SmoothCast is not installed under {VENV}. Run the setup script first."
        )
    return candidate


def runtime_ready() -> bool:
    """True when the selected runtime can start without setup."""
    if managed_target() is not None:
        return True  # the activated generation already passed its health probe
    runtime = runtime_python()
    if runtime is None:
        return False
    try:
        # MSYS2 DLLs and Homebrew typelibs must be available to the probe,
        # not only to the final GUI process. An invalid manifest fails closed.
        env = runtime_environment()
        for check in (RUNTIME_CHECK, bootstrap.PROJECT_DEPENDENCIES_CHECK):
            result = subprocess.run(
                [str(runtime), "-c", check], env=env,
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode != 0:
                return False
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False
    return all(shutil.which(tool, path=env.get("PATH"))
               for tool in ("ffmpeg", "ffprobe", "ffplay"))


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
        env["MSYSTEM"] = "UCRT64"
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
    name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower() if argv else ""
    if len(argv) < 2 or not re.fullmatch(
            r"pythonw?(?:[0-9]+(?:\.[0-9]+)?)?(?:[a-z])?(?:\.exe)?", name):
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


def known_gui_script(candidate: str) -> bool:
    """Recognise a SmoothCast source tree, not just a matching filename."""
    try:
        path = Path(candidate)
        if not path.is_absolute() or path.name != "cast_control.py" or path.parent.name != "src":
            return False
        root = path.parent.parent
        return (path.is_file() and (root / "setup" / "launch.py").is_file()
                and 'name = "smoothcast"' in (root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def _portable_processes() -> list[tuple[int, list[str]]]:
    """Same-user (pid, argv) pairs where /proc does not exist (macOS, Windows).

    psutil when it is importable, otherwise ``ps`` on macOS. Anything that
    fails yields an empty list: unknown never means "a GUI is running".
    """
    found: list[tuple[int, list[str]]] = []
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        psutil = None
    if psutil is not None:
        try:
            me = psutil.Process(os.getpid()).username()
            for process in psutil.process_iter(["pid", "cmdline", "username"]):
                info = process.info
                if info.get("username") == me and info.get("cmdline"):
                    found.append((int(info["pid"]), list(info["cmdline"])))
        except Exception:  # AccessDenied and platform errors must not block launch.
            return []
        return found
    if sys.platform == "darwin" and hasattr(os, "getuid"):
        try:
            out = subprocess.run(["ps", "-ww", "-U", str(os.getuid()), "-o", "pid=,command="],
                                 capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdecimal():
                # ps flattens argv; callers match by exact script path tokens.
                found.append((int(parts[0]), ["\0flat", parts[1]]))
    return found


def _flat_argv(command: str, target: str) -> list[str] | None:
    """Rebuild [python, ..., target] from a flattened ps command, or None."""
    index = command.find(target)
    while index > 0:
        end = index + len(target)
        if command[index - 1] == " " and (end == len(command) or command[end] == " "):
            return command[:index].split() + [target] + command[end:].split()
        index = command.find(target, index + 1)
    return None


def gui_instances(proc_root: Path = Path("/proc"),
                  exclude: set[int] | None = None, *,
                  all_installations: bool = False,
                  target: Path | None = None) -> list[int]:
    """Same-user GUI PIDs; optionally include recognised other installations."""
    target = str((target or ROOT / "src" / "cast_control.py").resolve())
    skip = {os.getpid()} | ({os.getppid()} if hasattr(os, "getppid") else set()) | (exclude or set())
    found: list[int] = []
    if not proc_root.is_dir():  # not Linux: enumerate through psutil / ps
        for pid, argv in _portable_processes():
            if pid in skip:
                continue
            if argv[:1] == ["\0flat"]:
                rebuilt = _flat_argv(argv[1], target)
                argvs = [rebuilt] if rebuilt else []
                if all_installations and not argvs:
                    argvs = [a for a in (
                        _flat_argv(argv[1], token) for token in argv[1].split()
                        if token.endswith("cast_control.py")) if a]
                argv_options = argvs
            else:
                argv_options = [argv]
            for candidate in argv_options:
                if is_gui_python_command(candidate, target) or (
                    all_installations and any(
                        is_gui_python_command(candidate, argument) and known_gui_script(argument)
                        for argument in candidate[1:])):
                    found.append(pid)
                    break
        return found
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
        if is_gui_python_command(argv, target) or (
            all_installations and any(
                is_gui_python_command(argv, argument) and known_gui_script(argument)
                for argument in argv[1:]
            )
        ):
            found.append(int(entry.name))
    return found


def activate_existing(timeout: float = 6.0) -> bool | None:
    """Ask the running instance to show its window.

    True when it accepted (window raised), False when it refused or timed out,
    and None when the running instance cannot be probed safely.
    """
    if sys.platform != "linux":
        return None  # no session bus to ask: the caller reports the running copy
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


# A relaunch of an already-running instance asks the primary to bounce its
# background services in place (room, mesh, library indexer, heartbeat, MPRIS)
# so a changed checkout or settings take effect without interrupting playback.
RELOAD_SERVICES_ARG = "--reload-services"


def ensure_single_instance(args: list[str], target: Path | None = None,
                           reclaim=None) -> int | None:
    """Exit code to stop launching, or None to start a new instance.

    `reclaim(pids)` may replace a primary that refuses activation (hung); it
    must verify identity itself and return True only when they are all gone.
    """
    pids = gui_instances(all_installations=True)
    if not pids:
        return None
    # Do not mistake successful activation of a different source tree for
    # successful startup of the selected installed runtime.
    if target is None:
        managed = managed_target()
        if managed is not None:
            target = managed[1]
    selected = set(gui_instances(target=target))
    activated = activate_existing()
    if activated and set(pids) - selected:
        print(
            "SmoothCast is running from another installation or checkout. "
            "Close that instance to start the selected installed version: "
            f"{ROOT}", file=sys.stderr,
        )
        return 3
    if activated:
        # A confirmed primary owns the application id. Let this launch forward
        # its command line so the running instance bounces its services in
        # place and opens any files; GApplication never starts a second window.
        if RELOAD_SERVICES_ARG not in args:
            args.append(RELOAD_SERVICES_ARG)
        return None
    # A primary can exit normally while the activation request is in flight.
    # Re-scan instead of leaving a false stale-instance failure behind.
    if not gui_instances(all_installations=True):
        return None
    # A D-Bus refusal/timeout is only a hint: PIDs can be reused. `reclaim`
    # re-verifies birth time and argv per process. Without it, or when the
    # probe itself was unavailable (None), preserve a possibly active cast.
    if reclaim is not None and activated is False and reclaim(gui_instances(all_installations=True)):
        return None
    print(
        "SmoothCast is already running but its window could not be activated. "
        "The existing process was left untouched. Close it normally (or use "
        "your system process manager if it is unresponsive), then retry.",
        file=sys.stderr,
    )
    return 3


def managed_target() -> tuple[Path, Path] | None:
    """The activated generation's ``(python, app)``, or None for the flat install.

    Settles any interrupted activation first; every failure falls back so a
    broken managed install can never stop SmoothCast from launching.
    """
    try:
        if not managed_startup.activated(ROOT):
            return None
        managed_startup.settle(ROOT)
        return managed_startup.active_launch(ROOT)
    except Exception:  # noqa: BLE001 - launch must never depend on the updater
        return None


def run_managed(root: Path, command: list[str], env: dict[str, str]) -> int:
    """Start the activated generation and confirm its exact commit.

    The launcher stays resident so it can acknowledge the switch the moment the
    primary publishes the commit it loaded; a generation that never confirms is
    rolled back by ``managed_startup.settle`` on the next launch.
    """
    try:
        pending = managed_startup.pending(root)
    except Exception:  # noqa: BLE001 - a corrupt journal is settled, not fatal
        pending = None
    ready_dir = None
    if pending is not None:
        ready_dir = tempfile.mkdtemp(prefix="smoothcast-activation-")
        os.chmod(ready_dir, 0o700)
        env[managed_startup.READY_ENV] = str(Path(ready_dir) / "ready")
    try:
        if os.name != "nt":
            os.chdir(root)
        process = subprocess.Popen(command, cwd=str(root), env=env)
        if pending is not None:
            txn, commit = pending
            managed_startup.await_acknowledgement(
                root, txn, commit, Path(env[managed_startup.READY_ENV]))
        return process.wait()
    finally:
        if ready_dir is not None:
            shutil.rmtree(ready_dir, ignore_errors=True)


def recovery_web(exit_code: int) -> int:
    """Keep a local, read-only recovery page alive after a desktop crash.

    No GTK, media tools, app imports, LAN advertisement or receiver commands.
    The terminal still owns this process; Ctrl+C stops the recovery server.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer

    page = (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>SmoothCast recovery</title>"
        "<main><h1>SmoothCast recovery mode</h1>"
        f"<p>Desktop startup failed or the process exited with status {int(exit_code)}.</p>"
        "<p>The casting engine and shared room are unavailable. "
        "This page is local diagnostics only, not an active room.</p>"
        "<p>Read the terminal error, stop recovery with Ctrl+C, "
        "then retry <code>python3 sc.py</code>.</p></main></html>"
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(3)
            super().setup()

        def do_GET(self):
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                self.send_error(403)
                return
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *_args):
            pass

    try:
        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            print(f"SmoothCast recovery web URL: http://127.0.0.1:{server.server_port}/ "
                  "(local only; casting unavailable). Ctrl+C to stop.",
                  file=sys.stderr, flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        print(f"SmoothCast recovery web unavailable: {exc}", file=sys.stderr, flush=True)
    return exit_code


def _desktop_exit(code: int) -> int:
    if code in (0, 130, -2, -15):
        return code  # normal exit or operator interrupt/termination
    print(f"SmoothCast: desktop failed with status {code}.", file=sys.stderr, flush=True)
    if gui_instances(all_installations=True):
        print("SmoothCast: another primary is still present; not starting recovery.",
              file=sys.stderr, flush=True)
        return code
    return recovery_web(code)


def main(argv: list[str] | None = None, *, prechecked: bool = False) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Direct shortcut/launcher calls reach the same isolated demo as sc.py (#523):
    # before any single-instance check, so a real running SmoothCast is untouched.
    if any(arg == "--demo" or arg.startswith("--demo=") for arg in args):
        sys.path.insert(0, str(ROOT / "src"))
        import demo_launch
        if args != ["--demo"]:
            return demo_launch.run(args)
        try:
            return demo_launch.run(args, str(python_path()), runtime_environment())
        except (OSError, RuntimeError) as exc:
            print(f"SmoothCast demo could not start: {exc}", file=sys.stderr)
            return 1
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
    # An activated generation (managed install) runs instead of the flat tree.
    target = managed_target()
    app = target[1] if target is not None else ROOT / "src" / "cast_control.py"
    # Always activate/diagnose the existing primary BEFORE checking the venv.
    # Its environment may have been moved during an update, while it remains
    # healthy and able to forward the caller's request.
    if not prechecked:
        guarded = ensure_single_instance(args, app)
        if guarded is not None:
            return guarded
    try:
        installed = target[0] if target is not None else python_path()
    except FileNotFoundError as exc:
        print(f"SmoothCast: {exc}", file=sys.stderr, flush=True)
        return _desktop_exit(1)
    # GTK's process cwd is intentionally ROOT; preserve the caller's media
    # paths before os.chdir/Windows subprocess cwd changes that reference.
    media_args = media_arguments_from_caller(args, Path.cwd())
    command = [str(installed), str(app), *media_args]
    try:
        env = runtime_environment()
        if target is not None:
            # Keep the launcher resident to acknowledge the new primary.
            return _desktop_exit(run_managed(ROOT, command, env))
        # Supervise the desktop instead of replacing the launcher: even an
        # import error or native crash must leave a browser recovery path.
        return _desktop_exit(subprocess.call(command, cwd=ROOT, env=env))
    except (OSError, RuntimeError) as exc:
        print(f"SmoothCast could not start: {exc}", file=sys.stderr, flush=True)
        return _desktop_exit(1)


if __name__ == "__main__":
    raise SystemExit(main())
