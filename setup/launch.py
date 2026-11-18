"""Portable SmoothCast launcher using the environment created by setup/bootstrap.py.

This module never installs anything or mutates dependency state. It is safe as
the target of native desktop shortcuts and can diagnose incomplete installs.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

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
                     initial.get("SystemDrive", "C:") + "\\\\msys64"))
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
