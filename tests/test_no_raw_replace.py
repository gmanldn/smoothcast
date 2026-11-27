"""Ratchet: no new hand-rolled ``os.replace`` writers (ARCH-13, #701).

Persistent state goes through ``store.Store`` (atomic, fsynced, owner-only,
schema-versioned). Modules below still hold their own temp+rename code; the
counts only go down. When you migrate one to ``Store``, lower or delete its entry.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALLOWED = {
    "cache_privacy.py": 1,
    "cast_app_lifecycle.py": 1,
    "config_control.py": 1,
    "diagnostics.py": 1,
    "error_tail.py": 1,
    "house_fetch.py": 1,
    "link_provision.py": 1,
    "low_end_policy.py": 1,
    "mesh_acquisition_store.py": 2,
    "mesh_acquisition_transfer.py": 1,
    "node_trust.py": 1,
    "participant_panel.py": 1,
    "portal_uploads.py": 1,
    "receiver_memory.py": 2,
    "reliability_metrics.py": 1,
    "resident_profiles.py": 1,
    "server.py": 1,
    "store.py": 1,
    "stream_health.py": 1,
    "streamer_generation.py": 1,
    "subtitle_encoding.py": 1,
}


def test_no_new_raw_os_replace_writers():
    found = {}
    for path in (ROOT / "src").glob("*.py"):
        count = path.read_text(encoding="utf-8").count("os.replace(")
        if count:
            found[path.name] = count
    worse = {n: (c, ALLOWED.get(n, 0)) for n, c in found.items() if c > ALLOWED.get(n, 0)}
    assert not worse, f"use store.Store instead of a new os.replace writer (found, allowed): {worse}"
