"""Per-user, source-safe SmoothCast installation locations.

This is intentionally stdlib-only: the three native entrypoints acquire Python
before calling it. All writes are confined to the selected application tree;
the source checkout, its worktrees and user data are not an install target.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import sys
import tempfile

APP_DIRS = ("src", "setup", "scripts", "data")
APP_FILES = ("pyproject.toml", "setup.py", "smoothcast", "sc.py",
             "README.md", "LICENSE")
IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache",
           ".ruff_cache", ".tox", "build", "dist", ".coverage", ".DS_Store"}


def config_path(target: str, *, home: Path | None = None,
                env: dict[str, str] | None = None) -> Path:
    home = Path.home() if home is None else home
    env = os.environ if env is None else env
    if target == "windows":
        return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "SmoothCast" / "install-location"
    return Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "smoothcast" / "install-location"


def default_directory(target: str, *, home: Path | None = None,
                      env: dict[str, str] | None = None) -> Path:
    home = Path.home() if home is None else home
    env = os.environ if env is None else env
    if target == "linux":
        return home / ".local" / "opt" / "SmoothCast"
    if target == "macos":
        return home / "Applications" / "SmoothCast"
    if target == "windows":
        return Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local") / "Programs" / "SmoothCast"
    raise ValueError(f"Unknown platform: {target}")


def previous_directory(target: str, *, home: Path | None = None,
                       env: dict[str, str] | None = None) -> Path | None:
    pointer = config_path(target, home=home, env=env)
    try:
        saved = pointer.read_text(encoding="utf-8").strip()
        candidate = Path(saved).expanduser()
        if candidate.is_absolute() and (candidate / "setup" / "bootstrap.py").is_file():
            return candidate
    except (OSError, ValueError):
        pass
    return None


def select_directory(target: str, *, explicit: str | None = None,
                     yes: bool = False, check: bool = False,
                     home: Path | None = None,
                     env: dict[str, str] | None = None,
                     input_fn=None) -> Path:
    default = (Path(explicit).expanduser() if explicit else
               previous_directory(target, home=home, env=env) or
               default_directory(target, home=home, env=env))
    # --yes works in CI and from a Windows batch file with no open console.
    # --check must not prompt, write a saved path or create directories.
    if not explicit and not yes and not check and sys.stdin.isatty():
        prompt = input if input_fn is None else input_fn
        try:
            answer = prompt(f"Install SmoothCast to [{default}] (Enter for default): ").strip()
        except EOFError:
            answer = ""
        if answer:
            default = Path(answer).expanduser()
    # absolute() preserves the terminal symlink, unlike resolve(); validate first.
    return default.absolute()


def validate_destination(source: Path, destination: Path) -> None:
    if destination.is_symlink():
        raise ValueError("Refusing to install through a symbolic link")
    source = source.resolve()
    destination = destination.resolve()
    if (destination == Path(destination.anchor) or
            destination == Path.home().resolve() or
            destination == source or
            source in destination.parents or destination in source.parents):
        raise ValueError("Install directory must be separate from the source checkout and home root")
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("Install destination is not a directory")
        if any(destination.iterdir()):
            manifest = destination / "pyproject.toml"
            try:
                text = manifest.read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError("Directory contains another application or user files") from exc
            if ('name = "smoothcast"' not in text or
                    not (destination / "setup" / "bootstrap.py").is_file()):
                raise ValueError("Refusing to overwrite non-SmoothCast directory")


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED or name.endswith(".pyc")}


def _source_items(source: Path):
    for name in APP_DIRS + APP_FILES:
        path = source / name
        if path.exists():
            yield name, path


@contextmanager
def installed_sources(source: Path, destination: Path):
    """Replace only app-managed sources; restore previous sources on failure.

    Existing .venv, saved state and all non-managed files are never removed.
    New installations are deleted on failure only when this routine created
    the entire target. A separate randomly named backup is kept until commit.
    """
    validate_destination(source, destination)
    first = not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=".smoothcast-install-backup-",
                                   dir=destination.parent))
    saved: list[str] = []
    created: list[str] = []
    try:
        for name, source_path in _source_items(source):
            target_path = destination / name
            if source_path.is_symlink() or target_path.is_symlink():
                raise ValueError(f"Refusing symbolic-link installation item: {name}")
            if target_path.exists():
                # Atomic rename on one filesystem: preserves the old source
                # even when a later copy or package bootstrap fails.
                target_path.rename(backup / name)
                saved.append(name)
            created.append(name)
            if source_path.is_dir():
                shutil.copytree(source_path, target_path, symlinks=False, ignore=_ignore)
            else:
                shutil.copy2(source_path, target_path)
        yield
    except BaseException:
        for name in reversed(created):
            path = destination / name
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        for name in saved:
            (backup / name).rename(destination / name)
        if first:
            # Only delete a brand-new target if we created it.
            shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def remember_directory(target: str, destination: Path, *,
                       home: Path | None = None,
                       env: dict[str, str] | None = None) -> None:
    pointer = config_path(target, home=home, env=env)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    temporary = pointer.with_name(pointer.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(str(destination.resolve()) + "\n", encoding="utf-8")
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(pointer)
    finally:
        temporary.unlink(missing_ok=True)
