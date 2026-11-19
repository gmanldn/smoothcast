"""Headless, evidence-backed release qualification; never probes a device or GUI.

A check's 'pass' is usable only for the exact release commit with a dated,
traceable evidence URL. Missing/stale evidence is never silently treated as a pass.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "docs" / "release_qualification.json"
# key -> (area, human-readable label, release gate, requires physical evidence)
CHECKS = {
    "portable-python-310": ("CI", "Portable regressions · Python 3.10", True, False),
    "portable-python-313": ("CI", "Portable regressions · Python 3.13", True, False),
    "ffmpeg-runtime": ("Media", "FFmpeg decoder and filter integration", True, False),
    "mkv-sample": ("Media", "Representative MKV playback sample", True, False),
    "subtitle-srt-sample": ("Media", "SRT loading and subtitle render sample", True, False),
    "setup-linux": ("Installer", "Linux setup contract", True, False),
    "setup-macos": ("Installer", "macOS setup contract", True, False),
    "setup-windows": ("Installer", "Windows setup contract", True, False),
    "wheel-linux": ("Artifact", "Linux installed wheel", True, False),
    "wheel-macos": ("Artifact", "macOS installed wheel", True, False),
    "wheel-windows": ("Artifact", "Windows installed wheel", True, False),
    "gtk-isolated": ("GTK", "Isolated Xvfb GTK smoke", True, False),
    "cast-chromecast": ("Receiver", "Chromecast playback, seek, stop", True, True),
    "dlna-lg": ("Receiver", "LG DLNA MediaRenderer", False, True),
    "dlna-samsung": ("Receiver", "Samsung DLNA MediaRenderer", False, True),
    "dlna-sony": ("Receiver", "Sony DLNA MediaRenderer", False, True),
    "airplay-apple-tv": ("Receiver", "Apple TV AirPlay", False, True),
    "roku": ("Receiver", "Roku receiver", False, True),
}
STATUSES = frozenset({"pending", "pass", "fail", "unsupported"})
SHA = re.compile(r"[0-9a-f]{40}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")


class QualificationError(ValueError):
    """The qualification manifest cannot be trusted."""


def canonical_version(path: Path = ROOT / "src" / "version.py") -> str:
    """Read canonical version constants without importing GUI or executing source."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parts = {}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in {"MAJOR", "MINOR", "PATCH"}
                    and isinstance(node.value, ast.Constant)
                    and type(node.value.value) is int and node.value.value >= 0):
                parts[node.targets[0].id] = node.value.value
        if len(parts) != 3:
            raise QualificationError("Version constants missing from src/version.py")
        return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['PATCH']}"
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise QualificationError(f"Cannot read canonical version: {exc}") from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise QualificationError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"Cannot load {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("releases"), dict):
        raise QualificationError("Expected schema_version=1 and releases object")
    for release, entry in data["releases"].items():
        if not isinstance(release, str) or not VERSION.fullmatch(release):
            raise QualificationError(f"Invalid release key: {release!r}")
        validate_entry(release, entry)
    return data


def _is_https_url(value: object) -> bool:
    if not isinstance(value, str) or any(ch.isspace() for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _dated(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.tzinfo is not None and instant.utcoffset() is not None
    except ValueError:
        return False


def validate_entry(release: str, entry: object) -> None:
    if not isinstance(entry, dict) or not isinstance(entry.get("commit"), str) or not SHA.fullmatch(entry["commit"]):
        raise QualificationError(f"{release}: expected a full lowercase 40-character commit SHA")
    checks = entry.get("checks")
    if not isinstance(checks, dict):
        raise QualificationError(f"{release}: missing checks object")
    unknown = set(checks) - set(CHECKS)
    if unknown:
        raise QualificationError(f"{release}: unknown check IDs {sorted(unknown)}")
    for key, item in checks.items():
        if not isinstance(item, dict) or item.get("status") not in STATUSES:
            raise QualificationError(f"{release}/{key}: invalid status")
        status = item["status"]
        if status == "unsupported" and CHECKS[key][2]:
            raise QualificationError(f"{release}/{key}: a mandatory gate cannot be unsupported")
        if status in {"pass", "fail"}:
            if not _is_https_url(item.get("evidence")) or not _dated(item.get("checked_at")):
                raise QualificationError(f"{release}/{key}: dated HTTPS evidence required")
            if not isinstance(item.get("commit"), str) or not SHA.fullmatch(item["commit"]):
                raise QualificationError(f"{release}/{key}: full evidence commit required")
            if CHECKS[key][3] and (not str(item.get("device_model", "")).strip()
                                    or not str(item.get("notes", "")).strip()):
                raise QualificationError(f"{release}/{key}: device model and test notes required")
        if status == "unsupported" and not str(item.get("notes", "")).strip():
            raise QualificationError(f"{release}/{key}: unsupported requires a reason")
    failures = entry.get("known_failures", [])
    if not isinstance(failures, list):
        raise QualificationError(f"{release}: known_failures must be a list")
    for failure in failures:
        if not isinstance(failure, dict) or failure.get("status") not in {"open", "resolved"}:
            raise QualificationError(f"{release}: failure must have open/resolved status")
        if not isinstance(failure.get("summary"), str) or not failure["summary"].strip():
            raise QualificationError(f"{release}: failure summary missing")
        if not _is_https_url(failure.get("issue")):
            raise QualificationError(f"{release}: failure requires an HTTPS issue URL")


def summary(manifest: dict, release: str) -> dict:
    entry = manifest["releases"].get(release)
    if entry is None:
        statuses = {key: "pending" for key in CHECKS}
        return {"release": release, "commit": None, "recorded": False,
                "statuses": statuses, "checks": {}, "known_failures": [], "ready": False,
                "blocked": False, "pending_required": sum(v[2] for v in CHECKS.values())}
    validate_entry(release, entry)
    statuses = {}
    for key in CHECKS:
        item = entry["checks"].get(key, {})
        status = item.get("status", "pending")
        # Evidence from another commit is never current evidence.
        if status in {"pass", "fail"} and item.get("commit") != entry["commit"]:
            status = "stale"
        statuses[key] = status
    failures = [f for f in entry.get("known_failures", []) if f["status"] == "open"]
    required_missing = sum(statuses[key] != "pass" for key, value in CHECKS.items() if value[2])
    blocked = bool(failures or "fail" in statuses.values())
    return {"release": release, "commit": entry["commit"], "recorded": True,
            "statuses": statuses, "checks": entry["checks"],
            "known_failures": failures, "ready": not blocked and required_missing == 0,
            "blocked": blocked, "pending_required": required_missing}


def markdown(result: dict) -> str:
    state = ("QUALIFIED (required gates)" if result["ready"] else
             "BLOCKED" if result["blocked"] else "NOT QUALIFIED")
    lines = [f"# SmoothCast {result['release']} — release qualification",
             "", f"**Status:** {state}",
             f"**Commit:** `{result['commit'] or 'not recorded'}`",
             "**Source:** version-specific evidence manifest; never infer test success from a source checkout.",
             "", "| Area | Check | Required | Result | Evidence |",
             "| --- | --- | --- | --- | --- |"]
    for key, (area, label, required, _physical) in CHECKS.items():
        status = result["statuses"][key].upper()
        item = result["checks"].get(key, {})
        url = item.get("evidence") if status not in {"PENDING"} else None
        evidence = f"[report]({url})" if _is_https_url(url) else "—"
        if status == "STALE":
            evidence = f"stale commit; {evidence}"
        elif status == "UNSUPPORTED":
            evidence = str(item.get("notes", "not supported")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {area} | {label} | {'Yes' if required else 'No'} | {status} | {evidence} |")
    lines += ["", f"**Missing required passes:** {result['pending_required']}",
              f"**Unresolved known failures:** {len(result['known_failures'])}", ""]
    if result["known_failures"]:
        lines.append("## Known failures")
        for failure in result["known_failures"]:
            label = failure["summary"].replace("\n", " ").replace("|", "\\|")
            lines.append(f"- {label} — [issue]({failure['issue']})")
        lines.append("")
    lines.append("Physical receiver checks require named hardware and recorded results; CI cannot replace them.")
    return "\n".join(lines) + "\n"


def init_release(manifest: dict, release: str, sha: str) -> None:
    if not VERSION.fullmatch(release) or not SHA.fullmatch(sha):
        raise QualificationError("--init requires semantic --release and lowercase 40-char --sha")
    if release in manifest["releases"]:
        raise QualificationError(f"Release {release} already exists; refusing to overwrite evidence")
    manifest["releases"][release] = {"commit": sha, "checks": {}, "known_failures": []}


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".qualification-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--release", help="Semantic release (default: current src/version.py)")
    parser.add_argument("--init", action="store_true", help="Create a pending record; never overwrite")
    parser.add_argument("--sha", help="Exact 40-character commit SHA required by --init")
    parser.add_argument("--output", type=Path, help="Write Markdown report instead of stdout")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero unless qualified")
    args = parser.parse_args(argv)
    try:
        release = args.release or canonical_version()
        if not VERSION.fullmatch(release):
            raise QualificationError("Release must be MAJOR.MINOR.PATCH")
        manifest = load_manifest(args.manifest)
        if args.init:
            if not args.sha:
                raise QualificationError("--init requires --sha")
            init_release(manifest, release, args.sha)
            atomic_write(args.manifest, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        elif args.sha:
            raise QualificationError("--sha may only be used with --init")
        report = summary(manifest, release)
        output = markdown(report)
        if args.output:
            if args.output.resolve() == args.manifest.resolve():
                raise QualificationError("Report output must not overwrite its evidence manifest")
            atomic_write(args.output, output)
            print(f"Wrote {args.output}: {'qualified' if report['ready'] else 'not qualified'}")
        else:
            sys.stdout.write(output)
        return 1 if args.strict and not report["ready"] else 0
    except QualificationError as exc:
        print(f"Release qualification error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
