#!/usr/bin/env python3
"""Prove the A -> B MSI upgrade and downgrade rejection on disposable Windows (#535).

Fixtures are built by ``build_windows_msi.py --fixture-version`` (increasing
ProductVersion, same permanent UpgradeCode). The exact-release
install/repair/uninstall smoke lives in ``smoke_windows_msi.py``; this only
proves the upgrade/rollback semantics from #532 that the smoke report leaves
``upgrade: untested``. Reuses ``msi_install_contract`` primitives; never opens a
GUI or a receiver. ``--dry-run`` writes the evidence contract off Windows.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msi_install_contract import (  # noqa: E402
    InstallerError, installer_command, run_installer, verify_candidate,
)
from smoke_windows_msi import require_disposable  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "smoothcast-windows-msi-upgrade/1"
DISPLAY_NAME = "SmoothCast"
_UNINSTALL = ("$ErrorActionPreference = 'Stop'; Get-ItemProperty "
              "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*' "
              f"| Where-Object {{ $_.DisplayName -eq '{DISPLAY_NAME}' }} "
              "| Select-Object -ExpandProperty DisplayVersion")


class UpgradeError(InstallerError):
    """The upgrade matrix could not run or an invariant did not hold."""


def fixture_versions(base: str) -> tuple[str, str]:
    """Two increasing three-field MSI versions (A, B) for temporary fixtures."""
    parts = base.split(".")
    if len(parts) != 3 or not all(part.isdecimal() for part in parts):
        raise UpgradeError(f"{base!r} is not a three-field version")
    major, minor, build = (int(part) for part in parts)
    if major > 255 or minor > 255 or build > 65535:
        raise UpgradeError(f"{base} is outside the MSI limits 255.255.65535")
    if build < 65535:
        nxt = f"{major}.{minor}.{build + 1}"
    elif minor < 255:
        nxt = f"{major}.{minor + 1}.0"
    elif major < 255:
        nxt = f"{major + 1}.0.0"
    else:
        raise UpgradeError("no representable higher MSI fixture version")
    return f"{major}.{minor}.{build}", nxt


def plan() -> list[dict]:
    """The ordered upgrade steps; ``reject`` steps must fail instead of passing."""
    return [
        {"name": "install_fixture_a", "action": "install", "fixture": "a"},
        {"name": "registered_version_a", "action": "expect_version", "fixture": "a"},
        {"name": "upgrade_to_fixture_b", "action": "install", "fixture": "b"},
        {"name": "registered_version_b", "action": "expect_version", "fixture": "b"},
        {"name": "downgrade_to_a_rejected", "action": "reject", "fixture": "a"},
        {"name": "uninstall_fixture_b", "action": "uninstall", "fixture": "b"},
    ]


def parse_registered_version(text: str) -> str:
    """Require at most one registered SmoothCast product."""
    versions = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(versions) > 1:
        raise UpgradeError("multiple SmoothCast products registered")
    return versions[0] if versions else ""


def registered_version(run=subprocess.run) -> str:
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _UNINSTALL],
                 capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise UpgradeError("could not query registered MSI version")
    return parse_registered_version(result.stdout)


def step_record(spec: dict, *, ok: bool, detail: str) -> dict:
    return {"name": spec["name"], "action": spec["action"], "fixture": spec["fixture"],
            "status": "pass" if ok else "fail", "detail": detail}


def record(*, commit: str, version: str, os_build: str, runner: str, started: str,
           duration: float, fixtures: dict, steps: list[dict]) -> dict:
    return {"schema": SCHEMA, "commit": commit, "version": version, "os_build": os_build,
            "runner": runner, "started": started, "duration_seconds": round(duration, 3),
            "fixtures": fixtures, "steps": steps,
            "ok": len(steps) == len(plan()) and all(
                step["status"] == "pass" and all(step.get(key) == value for key, value in spec.items())
                for step, spec in zip(steps, plan())
            )}


def _operation(executable: Path, operation: str, msi: Path, log: Path) -> None:
    run_installer(installer_command(executable, operation, msi, log), timeout=300)


def _downgrade_rejected(executable: Path, msi: Path, log: Path) -> None:
    """A timeout, reboot or unrelated installer failure is not a policy rejection."""
    log.unlink(missing_ok=True)
    try:
        _operation(executable, "install", msi, log)
    except InstallerError as exc:
        if str(exc) != "Windows Installer failed (1603)" or not log.is_file():
            raise
        raw = log.read_bytes()
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
        if "A newer SmoothCast is already installed." not in raw.decode(encoding, errors="replace"):
            raise UpgradeError("downgrade failed without the expected policy rejection") from exc
    else:
        raise UpgradeError("downgrade was accepted")


def run_matrix(fixture_a: Path, fixture_b: Path, version_a: str, version_b: str, *,
               report: Path, os_build: str, runner: str, commit: str,
               run=subprocess.run) -> dict:
    require_disposable(dict(os.environ), platform.system())
    windows = Path(os.environ["SystemRoot"]).resolve(strict=True)
    executable = windows / "System32" / "msiexec.exe"
    if not executable.is_file():
        raise UpgradeError("trusted system msiexec missing")
    if registered_version(run):
        raise UpgradeError("existing SmoothCast registration; target is not clean")
    fixture_a, fixture_b = fixture_a.absolute(), fixture_b.absolute()
    if (version_a, version_b) != fixture_versions(version_a):
        raise UpgradeError("fixtures must have consecutive canonical MSI versions")
    digests = {"a": _fixture_digest(fixture_a), "b": _fixture_digest(fixture_b)}
    if digests["a"] == digests["b"]:
        raise UpgradeError("upgrade fixtures must have distinct SHA-256 digests")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    began = time.monotonic()
    steps: list[dict] = []
    report.parent.mkdir(parents=True, exist_ok=True)
    logs = report.parent / "msi-upgrade-logs"
    logs.mkdir(exist_ok=True)
    fixtures = {"a": fixture_a, "b": fixture_b}
    for spec in plan():
        msi = fixtures[spec["fixture"]]
        expected = version_a if spec["fixture"] == "a" else version_b
        try:
            action = spec["action"]
            log = logs / f"{spec['name']}.log"
            if action in {"install", "uninstall"}:
                verify_candidate(msi, digests[spec["fixture"]])
                _operation(executable, action, msi, log)
                if action == "uninstall" and registered_version(run):
                    raise UpgradeError("uninstall left a registered SmoothCast product")
                steps.append(step_record(spec, ok=True, detail=f"{action} returned 0"))
            elif action == "expect_version":
                found = registered_version(run)
                if found != expected:
                    raise UpgradeError(f"registered {found!r}, expected {expected!r}")
                steps.append(step_record(spec, ok=True, detail=f"registered {found!r}"))
            elif action == "reject":
                verify_candidate(msi, digests[spec["fixture"]])
                _downgrade_rejected(executable, msi, log)
                if registered_version(run) != version_b:
                    raise UpgradeError("downgrade rejection did not preserve fixture B")
                steps.append(step_record(spec, ok=True, detail="downgrade policy rejected A; B retained"))
            else:
                raise UpgradeError(f"unknown matrix operation: {action}")
        except (InstallerError, OSError, subprocess.SubprocessError) as exc:
            steps.append(step_record(spec, ok=False, detail=str(exc)))
            break
    return record(commit=commit, version=version_a, os_build=os_build, runner=runner,
                  started=started, duration=time.monotonic() - began, fixtures=digests, steps=steps)


def _fixture_digest(path: Path) -> str:
    """Require the checksum emitted by the MSI builder, not a self-computed expectation."""
    checksum = path.with_name(path.name + ".sha256")
    if checksum.is_symlink() or not checksum.is_file():
        raise UpgradeError("missing regular MSI fixture checksum")
    try:
        fields = checksum.read_text(encoding="ascii").split()
    except UnicodeError as exc:
        raise UpgradeError("invalid MSI fixture checksum encoding") from exc
    if len(fields) != 2 or fields[1] != path.name:
        raise UpgradeError("MSI fixture checksum filename mismatch")
    return verify_candidate(path, fields[0])


def dry_run(version_a: str, version_b: str, fixtures: dict) -> dict:
    steps = [step_record(spec, ok=False, detail="untested") for spec in plan()]
    for step in steps:
        step["status"] = "untested"
    named = {name: str(path) for name, path in fixtures.items()}
    return record(commit="", version=version_a, os_build="", runner="dry-run",
                  started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), duration=0.0,
                  fixtures=named, steps=steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture-a", type=Path, required=True)
    parser.add_argument("--fixture-b", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--base-version", required=True, help="the lower A version")
    parser.add_argument("--commit", default="")
    parser.add_argument("--runner", default="")
    parser.add_argument("--os-build", default="")
    parser.add_argument("--dry-run", action="store_true",
                        help="write the untested contract without running msiexec")
    options = parser.parse_args(argv)
    try:
        version_a, version_b = fixture_versions(options.base_version)
        fixtures = {"a": options.fixture_a, "b": options.fixture_b}
        if options.dry_run:
            result = dry_run(version_a, version_b, fixtures)
        else:
            result = run_matrix(options.fixture_a, options.fixture_b, version_a, version_b,
                                report=options.report, os_build=options.os_build,
                                runner=options.runner, commit=options.commit)
    except (InstallerError, OSError, subprocess.SubprocessError) as exc:
        print(f"MSI upgrade matrix failed: {exc}", file=sys.stderr)
        return 1
    options.report.parent.mkdir(parents=True, exist_ok=True)
    options.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8", newline="\n")
    passed = sum(1 for step in result["steps"] if step["status"] == "pass")
    print(f"{result['schema']}: {passed}/{len(result['steps'])} passed -> {options.report}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
