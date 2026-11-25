"""Headless Windows Installer primitives for disposable-target CI (#535).

No CLI entry point: the lifecycle harness must explicitly opt in to mutation
on a disposable Windows target. These functions do not launch SmoothCast.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess


class InstallerError(RuntimeError):
    """Candidate validation or Windows Installer operation failed."""


def verify_candidate(msi: Path, expected_sha256: str) -> str:
    """Validate the exact downloaded MSI before handing it to Windows Installer."""
    if not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256):
        raise InstallerError("invalid expected MSI SHA-256")
    if msi.suffix.lower() != ".msi" or msi.is_symlink() or not msi.is_file():
        raise InstallerError("expected a regular MSI candidate file")
    digest = hashlib.sha256()
    with msi.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected_sha256.lower():
        raise InstallerError("MSI SHA-256 mismatch; refusing installation")
    return actual


def installer_command(executable: Path, operation: str, msi: Path, log: Path) -> list[str]:
    """Construct noninteractive, non-rebooting argv; no shell or GUI."""
    if operation not in {"install", "repair", "uninstall"}:
        raise InstallerError("unsupported MSI operation")
    if not all(path.is_absolute() for path in (executable, msi, log)):
        raise InstallerError("MSI command requires absolute paths")
    if executable.name.lower() != "msiexec.exe" or msi.suffix.lower() != ".msi":
        raise InstallerError("invalid Windows Installer executable or package")
    if log.suffix.lower() != ".log" or log == msi:
        raise InstallerError("invalid MSI log destination")
    switch = {"install": "/i", "repair": "/fa", "uninstall": "/x"}[operation]
    return [str(executable), switch, str(msi), "/qn", "/norestart", "/L*v", str(log)]


def run_installer(command: list[str], *, timeout: int = 180, run=subprocess.run) -> int:
    """Run a prepared command with a deadline and fail on any nonzero exit.

    3010 is not a clean pass: the target must be rebooted and requalified.
    1641 indicates an unexpected reboot. A timeout leaves target state unknown;
    callers must discard the disposable target, not continue the matrix.
    """
    if not 1 <= timeout <= 600:
        raise InstallerError("MSI timeout must be 1–600 seconds")
    try:
        result = run(command, stdin=subprocess.DEVNULL, capture_output=True,
                     timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise InstallerError("MSI operation timed out; discard the target") from exc
    except OSError as exc:
        raise InstallerError("could not start Windows Installer") from exc
    if result.returncode == 3010:
        raise InstallerError("MSI requires reboot (3010); target not qualified")
    if result.returncode == 1641:
        raise InstallerError("MSI initiated an unexpected reboot (1641)")
    if result.returncode != 0:
        raise InstallerError(f"Windows Installer failed ({result.returncode})")
    return result.returncode
