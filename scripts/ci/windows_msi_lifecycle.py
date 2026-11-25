#!/usr/bin/env python3
"""Drive a disposable Windows install/upgrade/repair/uninstall matrix (#535).

Pure planning and evidence recording live here and are unit-tested; the
msiexec runner is a thin, bounded wrapper that only executes on native
Windows. Nothing here opens a GUI, touches a receiver or changes the firewall.

``--dry-run`` writes the same evidence record with every step marked
``untested`` so the JSON contract can be exercised without Windows; that record
is never "green". The real run accepts only the documented Windows Installer
exit codes and writes ``dist/windows-msi-test-results.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS = ROOT / "dist" / "windows-msi-test-results.json"
SCHEMA = "smoothcast-windows-msi-tests/1"
REBOOT_REQUIRED = 3010                       # ERROR_SUCCESS_REBOOT_REQUIRED
MSI_VERBS = {"install": "/i", "repair": "/fa", "uninstall": "/x"}
STEP_TIMEOUT = 900
_USERS = re.compile(r"([A-Za-z]:\\Users\\)[^\\\s\"']+", re.IGNORECASE)
_TEMP = re.compile(r"(\\AppData\\Local\\Temp\\)[^\\\s\"']+", re.IGNORECASE)


class LifecycleError(RuntimeError):
    """The matrix cannot run here (wrong platform, bad input). Exit code 2."""


def fixture_versions(version: str) -> tuple[str, str]:
    """Two increasing three-field MSI versions (A, B) for temporary fixtures."""
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdecimal() for part in parts):
        raise LifecycleError(f"{version!r} is not a three-field version")
    major, minor, build = (int(part) for part in parts)
    if major > 255 or minor > 255 or build > 65535:
        raise LifecycleError(f"{version} is outside the MSI limits 255.255.65535")
    if build < 65535:
        nxt = f"{major}.{minor}.{build + 1}"
    elif minor < 255:
        nxt = f"{major}.{minor + 1}.0"
    else:
        nxt = f"{major + 1}.0.0"
    return f"{major}.{minor}.{build}", nxt


def plan() -> list[dict]:
    """The ordered lifecycle steps; each names an action and accepted exit codes."""
    return [
        {"name": "install_fixture_a", "action": "install", "fixture": "a",
         "accept": [0, REBOOT_REQUIRED]},
        {"name": "cli_version_a", "action": "cli", "fixture": "a", "accept": [0]},
        {"name": "upgrade_to_fixture_b", "action": "install", "fixture": "b",
         "accept": [0, REBOOT_REQUIRED]},
        {"name": "cli_version_b", "action": "cli", "fixture": "b", "accept": [0]},
        {"name": "repair_fixture_b", "action": "repair", "fixture": "b",
         "accept": [0, REBOOT_REQUIRED]},
        {"name": "uninstall_fixture_b", "action": "uninstall", "fixture": "b",
         "accept": [0, REBOOT_REQUIRED]},
        {"name": "install_dir_gone", "action": "absent", "fixture": "b", "accept": [0]},
    ]


def scrub(text: str) -> str:
    """Redact user and temp directory names so retained logs leak no paths."""
    return _TEMP.sub(r"\1<temp>", _USERS.sub(r"\1<user>", text or ""))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def msiexec_command(action: str, msi: Path, log: Path) -> list[str]:
    """One non-interactive, no-restart Windows Installer invocation."""
    return ["msiexec", MSI_VERBS[action], str(msi), "/qn", "/norestart",
            "/L*v", str(log)]


def step_record(spec: dict, *, exit_code: int | None, command: list[str],
                log: str, status: str) -> dict:
    return {"name": spec["name"], "action": spec["action"], "command": command,
            "exit_code": exit_code, "accept": list(spec["accept"]),
            "status": status, "log": scrub(log)}


def record(*, commit: str, version: str, os_build: str, runner: str, started: str,
           duration: float, fixtures: dict, steps: list[dict]) -> dict:
    return {"schema": SCHEMA, "commit": commit, "version": version, "os_build": os_build,
            "runner": runner, "started": started, "duration_seconds": round(duration, 3),
            "fixtures": fixtures, "steps": steps,
            "ok": bool(steps) and all(step["status"] == "pass" for step in steps)}


def _read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-8000:]
    except OSError:
        return ""


def execute(spec: dict, context: dict) -> tuple[int, list[str], str]:
    """Run one step and return (exit code, command, log tail). Windows only."""
    action = spec["action"]
    if action in MSI_VERBS:
        msi = context["fixtures"][spec["fixture"]]
        log = context["logs"] / f"{spec['name']}.log"
        command = msiexec_command(action, msi, log)
        result = subprocess.run(command, capture_output=True, text=True, timeout=STEP_TIMEOUT)
        return result.returncode, command, _read_log(log)
    if action == "cli":
        command = [str(context["install_dir"] / "SmoothCastCLI.exe"), "--version"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        return result.returncode, command, (result.stderr or result.stdout)[-2000:]
    if action == "absent":
        exists = context["install_dir"].exists()
        return (1 if exists else 0), ["test", "-e", str(context["install_dir"])], ""
    raise LifecycleError(f"unknown action {action!r}")


def run_matrix(fixtures: dict, *, install_dir: Path, logs: Path, os_build: str,
               runner: str, commit: str, version: str) -> dict:
    if sys.platform != "win32":
        raise LifecycleError("the MSI lifecycle needs native Windows (msiexec)")
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    began = time.monotonic()
    context = {"fixtures": fixtures, "install_dir": install_dir, "logs": logs}
    logs.mkdir(parents=True, exist_ok=True)
    steps = []
    for spec in plan():
        exit_code, command, log = execute(spec, context)
        status = "pass" if exit_code in spec["accept"] else "fail"
        steps.append(step_record(spec, exit_code=exit_code, command=command,
                                 log=log, status=status))
        if status == "fail":
            break
    hashes = {name: sha256(path) for name, path in fixtures.items() if path.is_file()}
    return record(commit=commit, version=version, os_build=os_build, runner=runner,
                  started=started, duration=time.monotonic() - began, fixtures=hashes,
                  steps=steps)


def dry_run(fixtures: dict, *, version: str, runner: str) -> dict:
    """The evidence shape with every step untested; never reported as green."""
    steps = [step_record(spec, exit_code=None, command=[], log="", status="untested")
             for spec in plan()]
    hashes = {name: sha256(path) for name, path in fixtures.items() if path.is_file()}
    return record(commit="", version=version, os_build="", runner=runner,
                  started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), duration=0.0,
                  fixtures=hashes, steps=steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture-a", type=Path, required=True)
    parser.add_argument("--fixture-b", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--logs", type=Path, default=ROOT / "build" / "msi" / "logs")
    parser.add_argument("--version", required=True, help="the base three-field version")
    parser.add_argument("--commit", default="")
    parser.add_argument("--runner", default="")
    parser.add_argument("--os-build", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--dry-run", action="store_true",
                        help="write the untested evidence contract without running msiexec")
    options = parser.parse_args(argv)
    fixtures = {"a": options.fixture_a, "b": options.fixture_b}
    try:
        fixture_versions(options.version)
        if options.dry_run:
            report = dry_run(fixtures, version=options.version, runner=options.runner)
        else:
            report = run_matrix(fixtures, install_dir=options.install_dir, logs=options.logs,
                                os_build=options.os_build, runner=options.runner,
                                commit=options.commit, version=options.version)
    except LifecycleError as exc:
        print(f"MSI lifecycle cannot run: {exc}", file=sys.stderr)
        return 2
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8", newline="\n")
    print(f"{report['schema']}: {sum(1 for s in report['steps'] if s['status'] == 'pass')}"
          f"/{len(report['steps'])} passed -> {options.output}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
