"""Ratchet: no new hard-coded home paths or ``cast-control`` literals (#701).

New code must take locations from ``paths.py``. Existing offenders are listed
with their current counts; the count may only go down. When you migrate a file,
lower or delete its entry.
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
PATTERN = re.compile(r"Path\.home\(\)|cast-control")
BASELINE = {
    "src/cast_lifecycle.py": 1,
    "src/cast_widgets.py": 1,
    "src/castctl.py": 4,
    "src/control_api.py": 1,
    "src/demo_session.py": 1,
    "src/diagnostics.py": 2,
    "src/library_folders.py": 1,
    "src/library_index.py": 1,
    "src/library_index_v2.py": 1,
    "src/link_sandbox_probe.py": 1,
    "src/mesh_library.py": 1,
    "src/mpris.py": 1,
    "src/portal_uploads.py": 1,
    "src/reliability_metrics.py": 3,
    "src/replica_store.py": 1,
    "src/server.py": 2,
    "src/shutdown_plan.py": 1,
    "src/smoothcast_assets/__init__.py": 1,
    "src/streamer.py": 3,
}


def _counts():
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "paths.py":
            continue
        n = len(PATTERN.findall(path.read_text(encoding="utf-8")))
        if n:
            found[path.relative_to(SRC.parent).as_posix()] = n
    return found


def test_no_new_hardcoded_paths():
    found = _counts()
    grown = {k: v for k, v in found.items() if v > BASELINE.get(k, 0)}
    assert not grown, f"use paths.py instead of hard-coded paths: {grown}"


def test_baseline_has_no_stale_entries():
    found = _counts()
    stale = {k: v for k, v in BASELINE.items() if found.get(k, 0) < v}
    assert not stale, f"lower these BASELINE entries: {stale}"
