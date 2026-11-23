#!/usr/bin/env python3
"""Startup import gate for the GUI entry module (issue #463).

Runs ``python -X importtime -c "import cast_control"`` in a scrubbed
environment (no display, no window is ever created) and fails when

* a denylisted heavy module is imported at startup (they must load on first
  use, after the first frame), or
* the number of modules imported, or the cumulative import time, exceeds the
  budget. The denylist and module count are deterministic and are the real
  gate; wall-clock import time is noisy (700-1300 ms on one machine), so its
  budget is deliberately loose (``SMOOTHCAST_IMPORT_SLACK`` scales it) and
  only catches large regressions.

    python3 scripts/ci/import_budget.py [--json]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ENTRY = "cast_control"
MAX_MODULES = 460            # measured 394 on 24 Nov 2026
MAX_MS = 3000.0              # measured 700-1300 ms depending on load; only catches disasters
# Loaded on first use, not at startup. Third-party first, then our own heavy stacks.
DENYLIST = ("zeroconf", "ifaddr", "pychromecast", "catt", "PIL", "requests", "numpy",
            "mesh_library", "library_index_v2", "search_engine", "federated_search",
            "replica_manager", "replica_store", "house_fetch")
_LINE = re.compile(r"import time:\s+(\d+) \|\s+(\d+) \| (\s*)(\S+)")


def parse(stderr: str) -> list[tuple[int, int, int, str]]:
    """(self_us, cumulative_us, depth, module) rows in log order."""
    rows = []
    for line in stderr.splitlines():
        match = _LINE.match(line)
        if match:
            rows.append((int(match.group(1)), int(match.group(2)),
                         len(match.group(3)) // 2, match.group(4)))
    return rows


def importer_chain(rows: list[tuple[int, int, int, str]], index: int) -> str:
    """'module <- parent <- grandparent' for the row at ``index``."""
    chain, depth = [rows[index][3]], rows[index][2]
    for later in rows[index + 1:]:
        if later[2] == depth - 1:
            chain.append(later[3])
            depth -= 1
        if depth == 0:
            break
    return " <- ".join(chain)


def evaluate(rows: list[tuple[int, int, int, str]], *, slack: float = 1.0,
             max_modules: int = MAX_MODULES, max_ms: float = MAX_MS,
             denylist: tuple[str, ...] = DENYLIST) -> dict:
    entry = [r for r in rows if r[2] == 0 and r[3] == ENTRY]
    total_ms = entry[0][1] / 1000 if entry else 0.0
    loaded = {r[3].split(".")[0]: i for i, r in reversed(list(enumerate(rows)))}
    banned = {name: importer_chain(rows, loaded[name]) for name in denylist if name in loaded}
    problems = []
    if not entry:
        problems.append(f"{ENTRY} was not imported")
    for name, chain in banned.items():
        problems.append(f"{name} is imported at startup ({chain}); load it on first use")
    if len(rows) > max_modules:
        problems.append(f"{len(rows)} modules imported at startup (budget {max_modules})")
    if total_ms > max_ms * slack:
        problems.append(f"{ENTRY} import took {total_ms:.0f} ms (budget {max_ms * slack:.0f} ms)")
    slowest = sorted((r for r in rows if r[2] == 1), key=lambda r: -r[1])[:8]
    return {"modules": len(rows), "import_ms": round(total_ms, 1), "problems": problems,
            "slowest": [{"module": r[3], "ms": round(r[1] / 1000, 1)} for r in slowest]}


def measure(src: Path = ROOT / "src") -> str:
    """Run the import in a clean subprocess and return its -X importtime log."""
    with tempfile.TemporaryDirectory(prefix="smoothcast-import-") as home:
        env = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BYPASS")}
        env.update(HOME=home, XDG_CONFIG_HOME=home, XDG_CACHE_HOME=home, XDG_DATA_HOME=home,
                   SMOOTHCAST_TEST_CONTEXT="1", GDK_BACKEND="x11", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-X", "importtime", "-c", f"import {ENTRY}"],
                                cwd=src, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"importing {ENTRY} failed:\n{result.stderr[-800:]}")
    return result.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    slack = float(os.environ.get("SMOOTHCAST_IMPORT_SLACK") or 1.0)
    try:
        report = evaluate(parse(measure()), slack=slack)
    except (RuntimeError, subprocess.SubprocessError) as exc:
        print(f"import budget: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{ENTRY}: {report['modules']} modules, {report['import_ms']} ms; "
              "slowest: " + ", ".join(f"{s['module']} {s['ms']} ms" for s in report["slowest"][:5]))
    for problem in report["problems"]:
        print(f"IMPORT BUDGET FAIL: {problem}", file=sys.stderr)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
