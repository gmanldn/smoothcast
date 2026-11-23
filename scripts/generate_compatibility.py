#!/usr/bin/env python3
"""Validate real-device records and render docs/DEVICE_COMPATIBILITY.md."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "devices"
DOC = ROOT / "docs" / "DEVICE_COMPATIBILITY.md"
STATUSES = {"passed", "failed", "not_tested"}
REQUIRED = {"id", "model", "protocol", "firmware", "smoothcast_version",
            "os", "date", "tester", "scenarios", "notes"}
OPTIONAL = {"issue"}


def load_records(directory: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")) if directory.exists() else []:
        with path.open(encoding="utf-8") as handle:
            item: Any = yaml.safe_load(handle)
        if not isinstance(item, dict):
            raise ValueError(f"{path}: record must be a YAML mapping")
        missing = REQUIRED - item.keys()
        extra = item.keys() - REQUIRED - OPTIONAL
        if missing or extra:
            raise ValueError(f"{path}: missing={sorted(missing)}, unknown={sorted(extra)}")
        if item["id"] != path.stem or not isinstance(item["id"], str):
            raise ValueError(f"{path}: id must match the filename")
        if item["id"] in seen:
            raise ValueError(f"{path}: duplicate id {item['id']!r}")
        seen.add(item["id"])
        if item["protocol"] not in {"cast", "dlna", "airplay", "roku"}:
            raise ValueError(f"{path}: unsupported protocol")
        try:
            date.fromisoformat(str(item["date"]))
        except ValueError as exc:
            raise ValueError(f"{path}: date must use YYYY-MM-DD") from exc
        scenarios = item["scenarios"]
        if not isinstance(scenarios, dict) or not scenarios:
            raise ValueError(f"{path}: scenarios must be a non-empty mapping")
        if any(not isinstance(k, str) or v not in STATUSES for k, v in scenarios.items()):
            raise ValueError(f"{path}: each scenario needs passed, failed, or not_tested")
        for field in ("model", "firmware", "smoothcast_version", "os", "tester", "notes"):
            if not isinstance(item[field], str):
                raise ValueError(f"{path}: {field} must be a string")
        records.append(item)
    return records


def render(records: list[dict[str, Any]]) -> str:
    lines = [
        "# Device compatibility", "",
        "Results reported by users and maintainers for specific receivers. Each row is",
        "one receiver on one SmoothCast version. **A row is evidence from a real device,",
        "not a guarantee.** CI never proves receiver behaviour (see",
        "[testing](agents/testing.md)).",
        "",
        "Submit a result with the [Device compatibility report](https://github.com/gmanldn/smoothcast/issues/new?template=device-report.yml) form.",
        "Only publish results that were observed on the named device; automated fakes",
        "and runner checks do not qualify receivers.", "",
        "Legend: ✅ passed · ❌ failed · ➖ not tested.", "",
        "| Receiver (make / model) | Protocol | Firmware | SmoothCast | Computer OS | Date / tester | Direct play | Transcode | Pause / seek | Subtitles | Volume | Other scenarios / notes | Report |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not records:
        lines.append("| *No verified receivers yet* | | | | | | | | | | | | |")
    for record in records:
        scenarios = record["scenarios"]
        icons = {"passed": "✅", "failed": "❌", "not_tested": "➖"}
        def status(*keys: str) -> str:
            for key in keys:
                if key in scenarios:
                    return icons[scenarios[key]]
            return "➖"
        known = {"direct_play", "transcode", "pause", "seek", "subtitles", "volume"}
        other = "; ".join(f"{name}: {icons[result]}" for name, result in scenarios.items()
                           if name not in known)
        if record["notes"]:
            other = f"{other}; {record['notes']}" if other else record["notes"]
        values = [record["model"], record["protocol"], record["firmware"] or "—",
                  record["smoothcast_version"], record["os"], f"{record['date']} / {record['tester']}",
                  status("direct_play"), status("transcode"),
                  f"pause {status('pause')} / seek {status('seek')}", status("subtitles"),
                  status("volume"), other or "—", f"[#{record['issue']}]" if "issue" in record else "—"]
        lines.append("| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |")
    lines += ["", "Records follow `docs/device-record.schema.json` and are stored in",
              "`data/devices/*.yaml`; regenerate this page with",
              "`python3 scripts/generate_compatibility.py`. Each record is dated and names",
              "the tester, device, firmware (when known), SmoothCast version and OS.", "",
              "Support tiers are assigned only from evidence: **Unverified** (no report),",
              "**Compatible** (community report), **Qualified** (maintainer verified),",
              "or **Known issues** (a reproducible failure is recorded). This table does",
              "not imply broader model-family support.", "",
              "Related: native DLNA hardware qualification is tracked in",
              "[#8](https://github.com/gmanldn/smoothcast/issues/8).", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the page is stale")
    args = parser.parse_args()
    try:
        expected = render(load_records(DATA_DIR))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Compatibility records invalid: {exc}", file=sys.stderr)
        return 2
    if args.check:
        if not DOC.exists() or DOC.read_text(encoding="utf-8") != expected:
            print("docs/DEVICE_COMPATIBILITY.md is stale; run scripts/generate_compatibility.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
