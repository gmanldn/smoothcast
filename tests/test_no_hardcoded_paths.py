"""Ratchet for #701: the legacy app directory name lives in paths.py.

The allowlist may only shrink. Move a file onto `paths` and delete its entry.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
ALLOWED = {
    "paths.py", "mpris.py", "control_api.py",  # mpris: a D-Bus desktop-entry id, not a path
    "demo_session.py", "demo_mode.py", 
    "receiver_memory.py", "reliability_metrics.py",
    "diagnostics.py", "streamer.py", "cast_portal_room.py",
    "cast_widgets.py", "doctor.py", "link_sandbox_probe.py", "low_end_policy.py",
    "portal_uploads.py", "server.py",
}


def test_cast_control_literal_only_in_allowlist():
    offenders = sorted(p.name for p in SRC.glob("*.py")
                       if "cast-control" in p.read_text(encoding="utf-8", errors="ignore")
                       and p.name not in ALLOWED)
    assert offenders == [], f"use paths.config_dir()/cache_dir(): {offenders}"
