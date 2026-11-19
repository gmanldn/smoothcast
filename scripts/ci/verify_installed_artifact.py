"""Prove the *shipped* SmoothCast artifact works without a Git checkout.

CI-only integration: build an sdist, build a wheel FROM that sdist, install in
a disposable dependency-free venv, then invoke entry points and import the
HLS helper/artwork from an unrelated cwd with no PYTHONPATH and no GTK.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SOURCE = Path(__file__).resolve().parents[2]
ICON = SOURCE / "data" / "cast-control.png"

# Always execute the installed code in a subprocess, not by importing from
# this script or appending SOURCE / src to sys.path.
VERIFY = r"""
import hashlib
import importlib.metadata as metadata
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve()
expected_icon_hash = sys.argv[2]
distribution = metadata.distribution("smoothcast")
import smoothcast_assets
import streamer
import server
import version

assert version.__version__ == distribution.version, (
    version.__version__, distribution.version
)
assert version.label() == f"v{distribution.version}"
assert sys.prefix != sys.base_prefix, "Must be the disposable virtualenv"

for module in (smoothcast_assets, streamer, server, version):
    path = Path(module.__file__).resolve()
    assert source not in (path, *path.parents), (
        "Imported uninstalled checkout code", path
    )

icon = smoothcast_assets.icon_path()
assert icon.is_file(), f"Missing bundled icon: {icon}"
assert icon.name == "local.cast-control.png"
data = icon.read_bytes()
assert data[:8] == b"\x89PNG\r\n\x1a\n", "Bundled icon is not PNG"
assert hashlib.sha256(data).hexdigest() == expected_icon_hash, (
    "Bundled icon differs from the original repository artwork"
)

helper = Path(streamer.SERVER_SCRIPT).resolve()
assert helper.is_file(), f"HLS server entry module missing: {helper}"
assert helper.samefile(Path(server.__file__).resolve())
assert server.public_resource("/movie.m3u8")
assert server.public_resource("/segment-00001.ts")
assert not server.public_resource("/session.json")
assert not server.public_resource("/../../config.json")

expected = {"smoothcast", "sc", "smoothcast-gui"}
commands = {item.name: item.value for item in distribution.entry_points}
assert expected <= commands.keys(), commands
assert all(commands[name] == "cli:main" for name in expected), commands
assert "gi" not in sys.modules, "Headless version/packaging check imported GTK"
print(f"Installed SmoothCast {distribution.version}: entry points, icon and HLS OK")
"""


def clean_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
        "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
        "XAUTHORITY",
    ):
        env.pop(key, None)
    env.update(
        PYTHONNOUSERSITE="1",
        SMOOTHCAST_TEST_CONTEXT="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
    )
    return env


def execute(args: list[str], *, cwd: Path, env: dict[str, str],
            timeout: int = 180) -> subprocess.CompletedProcess[str]:
    print(" > " + " ".join(str(part) for part in args), flush=True)
    result = subprocess.run(
        args, cwd=cwd, env=env, capture_output=True,
        text=True, timeout=timeout, check=False,
    )
    if result.returncode:
        print(result.stdout[-4500:], file=sys.stderr, flush=True)
        print(result.stderr[-4500:], file=sys.stderr, flush=True)
        raise RuntimeError(
            f"Installed artifact check exited {result.returncode}: {args[0]}"
        )
    return result


def entry_path(venv: Path, name: str) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


def main() -> int:
    if not ICON.is_file():
        raise RuntimeError("Repository's original icon is missing")
    icon_hash = hashlib.sha256(ICON.read_bytes()).hexdigest()
    env = clean_environment()
    with tempfile.TemporaryDirectory(prefix="smoothcast-artifact-ci-") as folder:
        work = Path(folder)
        # No installed command runs from the repository or an editable install.
        outside = work / "outside checkout with spaces"
        outside.mkdir()
        dist = work / "sdist"
        wheels = work / "wheels"
        dist.mkdir()
        wheels.mkdir()
        execute(
            [sys.executable, "-m", "build", "--sdist", "--no-isolation",
             "--outdir", str(dist), str(SOURCE)],
            cwd=outside, env=env,
        )
        archives = list(dist.glob("smoothcast-*.tar.gz"))
        if len(archives) != 1:
            raise RuntimeError(f"Expected one source release, found {archives}")
        # Important: build wheel from the source release, not directly from
        # the checkout or a stale source tree.
        execute(
            [sys.executable, "-m", "pip", "wheel", "--no-deps",
             "--no-build-isolation", "--wheel-dir", str(wheels),
             str(archives[0])],
            cwd=outside, env=env,
        )
        artifacts = list(wheels.glob("smoothcast-*.whl"))
        if len(artifacts) != 1:
            raise RuntimeError(f"Expected one built wheel, found {artifacts}")

        venv = work / "fresh installed runtime"
        execute([sys.executable, "-m", "venv", str(venv)],
                cwd=outside, env=env, timeout=90)
        python = (venv / "Scripts" / "python.exe" if os.name == "nt"
                  else venv / "bin" / "python")
        execute(
            [str(python), "-m", "pip", "install", "--no-index", "--no-deps",
             str(artifacts[0])],
            cwd=outside, env=env, timeout=90,
        )
        # No installed dependency is needed for the version/UI-free
        # contract; real GTK, catt and FFmpeg are checked separately.
        check = execute(
            [str(python), "-I", "-c", VERIFY, str(SOURCE), icon_hash],
            cwd=outside, env=env, timeout=30,
        )
        print(check.stdout.strip())
        expected = "SmoothCast v"
        for name in ("smoothcast", "sc", "smoothcast-gui"):
            entry = entry_path(venv, name)
            if not entry.is_file():
                raise RuntimeError(f"Missing wheel entry point: {entry}")
            result = execute(
                [str(entry), "--version"], cwd=outside, env=env, timeout=30,
            )
            # On Windows, gui_scripts use pythonw.exe and need not attach
            # stdout; successful non-GTK exit plus the installed metadata
            # contract above verifies that entry point.
            if os.name != "nt" or name != "smoothcast-gui":
                if not result.stdout.strip().startswith(expected):
                    raise RuntimeError(
                        f"{name} returned unexpected installed version: {result.stdout!r}"
                    )
        print("Installed artifact verified away from checkout, without GUI.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"Installed artifact verification failed: {exc}",
              file=sys.stderr, flush=True)
        raise SystemExit(1)
