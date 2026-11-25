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
_UNINSTALL = ("Get-ItemProperty "
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
    else:
        nxt = f"{major + 1}.0.0"
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
    """First non-blank line of ``Select-Object -ExpandProperty DisplayVersion``."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def registered_version(run=subprocess.run) -> str:
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _UNINSTALL],
                 capture_output=True, text=True, timeout=60)
    return parse_registered_version(result.stdout)


def step_record(spec: dict, *, ok: bool, detail: str) -> dict:
    return {"name": spec["name"], "action": spec["action"], "fixture": spec["fixture"],
            "status": "pass" if ok else "fail", "detail": detail}


def record(*, commit: str, version: str, os_build: str, runner: str, started: str,
           duration: float, fixtures: dict, steps: list[dict]) -> dict:
    return {"schema": SCHEMA, "commit": commit, "version": version, "os_build": os_build,
            "runner": runner, "started": started, "duration_seconds": round(duration, 3),
            "fixtures": fixtures, "steps": steps,
            "ok": bool(steps) and all(step["status"] == "pass" for step in steps)}


def _install(executable: Path, msi: Path, log: Path) -> None:
    run_installer(installer_command(executable, "install", msi, log), timeout=300)


def run_matrix(fixture_a: Path, fixture_b: Path, version_a: str, version_b: str, *,
               report: Path, os_build: str, runner: str, commit: str,
               run=subprocess.run) -> dict:
    require_disposable(dict(os.environ), platform.system())
    windows = Path(os.environ["SystemRoot"]).resolve(strict=True)
    executable = windows / "System32" / "msiexec.exe"
    if not executable.is_file():
        raise UpgradeError("trusted system msiexec missing")
    digests = {"a": verify_candidate(fixture_a, _sha(fixture_a)),
               "b": verify_candidate(fixture_b, _sha(fixture_b))}
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
            if spec["action"] in {"install", "uninstall"}:
                _install(executable, msi, logs / f"{spec['name']}.log")
                steps.append(step_record(spec, ok=True, detail=f"{spec['action']} returned 0"))
            elif spec["action"] == "expect_version":
                found = registered_version(run)
                steps.append(step_record(spec, ok=found == expected,
                                         detail=f"registered {found!r}, expected {expected!r}"))
            else:  # reject: a downgrade must not succeed
                try:
                    _install(executable, msi, logs / f"{spec['name']}.log")
                except InstallerError as exc:
                    steps.append(step_record(spec, ok=True, detail=f"rejected: {exc}"))
                else:
                    steps.append(step_record(spec, ok=False, detail="downgrade was accepted"))
        except (InstallerError, OSError, subprocess.SubprocessError) as exc:
            steps.append(step_record(spec, ok=False, detail=str(exc)))
            break
    return record(commit=commit, version=version_a, os_build=os_build, runner=runner,
                  started=started, duration=time.monotonic() - began, fixtures=digests, steps=steps)


def _sha(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
