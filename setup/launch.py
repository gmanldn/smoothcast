"""Portable SmoothCast launcher using the environment created by setup/bootstrap.py.

This module never installs anything or mutates dependency state. It is safe as
the target of native desktop shortcuts and can diagnose incomplete installs.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

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


def runtime_environment() -> dict[str, str]:
    env = dict(os.environ)
    if os.name == "nt":
        root = Path(os.environ.get("MSYS2_ROOT") or
                    os.environ.get("SystemDrive", "C:") + "\\msys64")
        ucrt = root / "ucrt64"
        env["PATH"] = os.pathsep.join(
            (str(ucrt / "bin"), str(root / "usr" / "bin"), env.get("PATH", "")),
        )
        env["PYGI_DLL_PATH"] = str(ucrt / "bin")
        typelib = ucrt / "lib" / "girepository-1.0"
        env["GI_TYPELIB_PATH"] = str(typelib)
        env["XDG_DATA_DIRS"] = os.pathsep.join(
            (str(ucrt / "share"), env.get("XDG_DATA_DIRS", "")),
        )
    elif sys.platform == "darwin":
        prefixes = (Path("/opt/homebrew"), Path("/usr/local"))
        installed = [p for p in prefixes if (p / "bin" / "brew").exists()]
        if installed:
            prefix = installed[0]
            env["PATH"] = os.pathsep.join(
                (str(prefix / "bin"), str(prefix / "sbin"), env.get("PATH", "")),
            )
            typelib = prefix / "lib" / "girepository-1.0"
            if typelib.is_dir():
                env["GI_TYPELIB_PATH"] = os.pathsep.join(
                    (str(typelib), env.get("GI_TYPELIB_PATH", "")),
                )
    return env


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        return subprocess.call([sys.executable, str(ROOT / "src" / "version.py")])
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
    command = [str(installed), str(ROOT / "src" / "cast_control.py"), *args]
    env = runtime_environment()
    try:
        if os.name != "nt":
            # A .desktop launch may inherit HOME or / as its working directory.
            # Use the same project root as the Windows launcher.
            os.chdir(ROOT)
            os.execvpe(command[0], command, env)
        return subprocess.call(command, cwd=ROOT, env=env)
    except OSError as exc:
        print(f"SmoothCast could not start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
