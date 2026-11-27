"""Run bounded, GUI-free smoke checks against the actual PyInstaller artefact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ICON = ROOT / "src" / "smoothcast_assets" / "local.cast-control.png"


def console_executable(dist: Path) -> Path:
    extension = ".exe" if sys.platform == "win32" else ""
    locations = (
        dist / "SmoothCast" / f"SmoothCastCLI{extension}",
        dist / "SmoothCast.app" / "Contents" / "MacOS" / "SmoothCastCLI",
    )
    for path in locations:
        if path.is_file():
            return path
    raise FileNotFoundError("SmoothCastCLI frozen artefact missing: " + ", ".join(map(str, locations)))


def check(executable: Path, arguments: list[str], expected: str) -> None:
    result = subprocess.run(
        [str(executable), *arguments], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, cwd=executable.parent,
    )
    if result.returncode != 0 or expected not in result.stdout:
        raise RuntimeError(
            f"{executable.name} {arguments!r} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout)[-1800:]}"
        )


def check_media_probe(executable: Path) -> None:
    """Prove the frozen CLI's media probe is wired and self-consistent (#530).

    Only ``<tool> -version`` runs; no media, display or receiver. The report
    deliberately omits paths, so this asserts the JSON contract and that the
    exit code agrees with ``ok`` (0 when every tool is usable, 1 otherwise).
    Whether the *bundled* tools exist is enforced by the Windows MSI gate
    (#529/#535); this check catches a broken or missing probe on any platform.
    """
    result = subprocess.run(
        [str(executable), "--_smoothcast-media-probe"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=30, cwd=executable.parent,
    )
    try:
        report = json.loads(result.stdout)
    except (TypeError, ValueError):
        raise RuntimeError(
            f"{executable.name} --_smoothcast-media-probe did not print JSON "
            f"({result.returncode}): {(result.stderr or result.stdout)[-1800:]}"
        )
    if not isinstance(report, dict) or "tools" not in report or "ok" not in report:
        raise RuntimeError(f"media probe JSON is missing 'tools'/'ok': {report!r}")
    expected = 0 if report["ok"] else 1
    if result.returncode != expected:
        raise RuntimeError(
            f"media probe exit {result.returncode} disagrees with ok={report['ok']}"
        )


def check_project_legal(executable: Path, source_root: Path = ROOT) -> None:
    """Check the actual frozen package contains the original legal notices."""
    if executable.parent.parent.name == "Contents":
        legal = executable.parent.parent / "Resources" / "legal"
    else:
        legal = executable.parent / "_internal" / "legal"
    for name, source in (
        ("LICENSE", source_root / "LICENSE"),
        ("SmoothCast-NOTICE.txt", source_root / "packaging" / "SmoothCast-NOTICE.txt"),
    ):
        packaged = legal / name
        if not packaged.is_file() or packaged.read_bytes() != source.read_bytes():
            raise RuntimeError(f"Missing or modified SmoothCast legal file: {packaged}")


def verify(dist: Path) -> None:
    executable = console_executable(dist)
    check_project_legal(executable)
    # Do not launch the normal GUI or the HLS server. All probes exit promptly.
    check(executable, ["--version"], "SmoothCast v")
    check(executable, ["--_smoothcast-catt", "--help"], "Usage:")
    expected = hashlib.sha256(ICON.read_bytes()).hexdigest()
    check(executable, ["--_smoothcast-package-check"], expected)
    check_media_probe(executable)


if __name__ == "__main__":
    verify(Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "dist")
