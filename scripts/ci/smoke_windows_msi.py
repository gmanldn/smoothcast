"""Headless install/repair/uninstall of the exact MSI on a disposable CI worker.

No GUI, receiver, real-user machine, or claim of a pristine offline VM.
Upgrade fixtures and physical Windows qualification are separate gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import re
import subprocess
import sys
import tempfile

from msi_install_contract import (
    InstallerError, installer_command, run_installer, verify_candidate,
)
from verify_frozen_artifact import ROOT, check_project_legal


def candidate_from(directory: Path) -> tuple[Path, str, str]:
    candidates = sorted(directory.glob("SmoothCast-*-x64.msi"))
    if len(candidates) != 1:
        raise InstallerError("expected exactly one versioned MSI")
    msi = candidates[0]
    name = re.fullmatch(r"SmoothCast-(\d+\.\d+\.\d+)-x64\.msi", msi.name)
    if not name:
        raise InstallerError("invalid canonical MSI filename")
    checksum = msi.with_name(msi.name + ".sha256")
    if checksum.is_symlink() or not checksum.is_file():
        raise InstallerError("missing regular MSI checksum")
    fields = checksum.read_text(encoding="ascii").split()
    if len(fields) != 2 or fields[1] != msi.name:
        raise InstallerError("MSI checksum filename mismatch")
    return msi.resolve(), verify_candidate(msi, fields[0]), name[1]


def require_disposable(environ: dict[str, str], system: str) -> None:
    required = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_OS": "Windows", "SMOOTHCAST_TEST_CONTEXT": "1"}
    if system != "Windows" or any(environ.get(k) != v for k, v in required.items()):
        raise InstallerError("MSI mutation allowed only on a disposable hosted Windows CI worker")


def runtime_environment(environ: dict[str, str], windows: Path) -> dict[str, str]:
    # No inherited Python, MSYS2, GTK, GI, GStreamer or FFmpeg developer paths.
    safe = {k: v for k, v in environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "USERNAME",
        "HOMEDRIVE", "HOMEPATH", "SMOOTHCAST_TEST_CONTEXT",
    }}
    safe["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    return safe


def cli_check(cli: Path, args: list[str], expected: str, env: dict[str, str],
              cwd: Path) -> None:
    result = subprocess.run([str(cli), *args], cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, errors="replace", timeout=60, check=False)
    if result.returncode or (expected and result.stdout.strip() != expected):
        raise InstallerError(f"installed CLI {args[0]} failed ({result.returncode})")


def check_installed_package(cli: Path, version: str, env: dict[str, str],
                            cwd: Path, source_root: Path = ROOT) -> None:
    """Verify the installed product against the checked-out source, not itself."""
    try:
        check_project_legal(cli, source_root)
        icon = source_root / "src" / "smoothcast_assets" / "local.cast-control.png"
        expected = hashlib.sha256(icon.read_bytes()).hexdigest()
    except (RuntimeError, OSError) as exc:
        raise InstallerError(f"installed legal files or source artwork invalid: {exc}") from exc
    cli_check(cli, ["--version"], "SmoothCast v" + version, env, cwd)
    cli_check(cli, ["--_smoothcast-package-check"], expected, env, cwd)


def _keep_logs(source: Path, destination: Path) -> None:
    """Keep msiexec logs and print the lines that explain a failure (UTF-16 or ANSI)."""
    for log in source.glob("*.log"):
        try:
            shutil.copy2(log, destination / log.name)
            raw = log.read_bytes()
            text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", "replace")
            lines = text.splitlines()
            hits = [i for i, line in enumerate(lines) if "Return value 3" in line or "Error " in line]
            for i in hits[:6]:
                print(f"--- {log.name} ---\n" + "\n".join(lines[max(0, i - 6):i + 2]), file=sys.stderr)
        except OSError:
            pass


def smoke(directory: Path, report: Path) -> None:
    require_disposable(dict(os.environ), platform.system())
    msi, digest, version = candidate_from(directory)
    windows = Path(os.environ["SystemRoot"]).resolve(strict=True)
    executable = windows / "System32" / "msiexec.exe"
    install = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "SmoothCast"
    shortcut = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" /
                "Start Menu" / "Programs" / "SmoothCast" / "SmoothCast.lnk")
    if install.exists() or shortcut.exists() or install.is_symlink():
        raise InstallerError("existing SmoothCast installation; target is not clean")
    if not executable.is_file():
        raise InstallerError("trusted system msiexec missing")
    evidence = {"source_commit": os.environ.get("GITHUB_SHA"), "version": version,
                "sha256": digest, "os": platform.version(),
                "target": "separate github-hosted Windows worker; sanitised CLI PATH",
                "upgrade": "untested", "physical_gui_cast": "untested",
                "offline_vm": "untested", "steps": {}}
    steps = evidence["steps"]
    env = runtime_environment(dict(os.environ), windows)
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="SmoothCast MSI smoke ") as temp:
            root = Path(temp)
            cli = install / "SmoothCastCLI.exe"
            gui = install / "SmoothCast.exe"
            try:
                for operation in ("install", "repair", "uninstall"):
                    # Reverify bytes immediately before every operation.
                    verify_candidate(msi, digest)
                    run_installer(installer_command(executable, operation, msi,
                                                    root / (operation + ".log")), timeout=300)
                    if operation == "uninstall":
                        if install.exists() or shortcut.exists():
                            raise InstallerError("MSI uninstall left app-owned installation or shortcut")
                    else:
                        if not all(p.is_file() for p in (cli, gui, shortcut)):
                            raise InstallerError("installed executable or Start Menu shortcut missing")
                        check_installed_package(cli, version, env, root)
                        current = hashlib.sha256(cli.read_bytes()).hexdigest()
                        if operation == "install":
                            original = current
                            cli.unlink()
                            (install / "_internal" / "legal" / "LICENSE").unlink()
                        elif current != original:
                            raise InstallerError("repair did not restore original CLI bytes")
                    steps[operation] = "pass"
            except (InstallerError, OSError, subprocess.SubprocessError):
                _keep_logs(root, report.parent)
                raise
    except (InstallerError, OSError, subprocess.SubprocessError):
        evidence["result"] = "fail"
        raise
    else:
        evidence["result"] = "pass"
    finally:
        report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--disposable-ci", action="store_true", required=True)
    args = parser.parse_args()
    try:
        smoke(args.candidate_dir, args.report)
    except (InstallerError, OSError, subprocess.SubprocessError) as exc:
        print(f"MSI lifecycle failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
