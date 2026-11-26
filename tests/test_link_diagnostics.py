"""Headless owner diagnostics for link workers; runs no program and no network."""
from __future__ import annotations

import link_acquisition as acquisition
import link_diagnostics as diag


def _ready(**kinds):
    base = {"enabled_by_owner": False, "missing": []}
    return {k: {**base, **kinds.get(k, {})} for k in ("youtube", "magnet")}


def _by(rows):
    return {r["kind"]: r for r in rows}


def test_missing_tools_are_named_with_platform_specific_repair():
    readiness = _ready(youtube={"missing": ["yt-dlp", "ffprobe", diag.LAUNCHER]})
    mac = _by(diag.rows(readiness, platform="darwin"))["youtube"]
    assert mac["status"] == "missing" and "yt-dlp" in mac["summary"]
    assert "brew install yt-dlp" in mac["repair"][0]
    win = _by(diag.rows(readiness, platform="win32"))["youtube"]
    assert "winget" in win["repair"][0]
    linux = _by(diag.rows(readiness, platform="linux2"))["youtube"]
    assert "package manager" in linux["repair"][0]
    assert "--link-check --setup" in linux["repair"][-1] and "SMOOTHCAST_LINK_SANDBOX" in linux["repair"][-1]


def test_off_restart_ready_and_failed_states():
    off = _by(diag.rows(_ready()))["youtube"]
    assert off["status"] == "off"
    on = _ready(youtube={"enabled_by_owner": True})
    assert _by(diag.rows(on, running=None))["youtube"]["status"] == "restart"
    assert _by(diag.rows(on, running={"youtube": True}))["youtube"]["status"] == "ready"
    failed = _by(diag.rows(on, running={"youtube": False, "magnet": False}))["youtube"]
    assert failed["status"] == "failed"


def test_ready_never_claims_isolation_was_verified():
    row = _by(diag.rows(_ready(youtube={"enabled_by_owner": True}), running={"youtube": True}))["youtube"]
    assert "cannot verify" in row["summary"] and "verified" not in row["summary"].replace("cannot verify", "")
    assert row["repair"] == ["run 'smoothcast --link-check --qualify' to attack-test the launcher before it is trusted"]


def test_ready_surfaced_isolation_verified_only_when_probe_passed():
    row = _by(diag.rows(_ready(youtube={"enabled_by_owner": True, "isolation_verified": True}),
                        running={"youtube": True}))["youtube"]
    assert "attack-test probe" in row["summary"] and "cannot verify" not in row["summary"]
    assert row["repair"] == []


def test_strict_gate_missing_entry_maps_to_qualify_step_not_install():
    readiness = _ready(youtube={"enabled_by_owner": True, "missing": [diag._QUALIFY]})
    row = _by(diag.rows(readiness, platform="linux"))["youtube"]
    assert row["status"] == "missing" and "qualified isolation" in row["summary"]
    assert row["repair"] == ["run 'smoothcast --link-check --qualify' to attack-test the launcher before it is trusted"]


def test_enabled_unverified_states_point_to_qualify_without_duplicates():
    enabled = _ready(youtube={"enabled_by_owner": True})
    assert _by(diag.rows(enabled, running=None))["youtube"]["repair"] == \
        ["run 'smoothcast --link-check --qualify' to attack-test the launcher before it is trusted"]
    assert _by(diag.rows(enabled, running={"youtube": False}))["youtube"]["repair"] == \
        ["run 'smoothcast --link-check --qualify' to attack-test the launcher before it is trusted"]
    verified = _ready(youtube={"enabled_by_owner": True, "isolation_verified": True})
    assert _by(diag.rows(verified, running=None))["youtube"]["repair"] == []


def test_subtitle_adds_only_the_first_repair_step():
    row = _by(diag.rows(_ready(magnet={"missing": ["aria2c", "ffprobe"]}), platform="linux"))["magnet"]
    text = diag.subtitle(row)
    assert "aria2" in text and "ffmpeg" not in text


def test_rows_match_the_real_provider_without_running_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: None)
    monkeypatch.delenv("SMOOTHCAST_LINK_SANDBOX", raising=False)
    provider = acquisition.CommandProvider(("youtube",))
    rows = _by(diag.rows(provider.readiness(), running=None, platform="linux"))
    assert rows["youtube"]["status"] == rows["magnet"]["status"] == "missing"
    assert diag.LAUNCHER in rows["youtube"]["summary"]


class _Switch:
    text = ""

    def set_subtitle(self, value):
        self.text = value


def test_describe_switches_labels_both_rows_and_tolerates_no_room(monkeypatch):
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: None)
    monkeypatch.delenv("SMOOTHCAST_LINK_SANDBOX", raising=False)
    switches = {"portal_link_youtube": _Switch(), "portal_link_magnet": _Switch()}
    diag.describe_switches(object(), {}, switches)
    assert "Missing: yt-dlp" in switches["portal_link_youtube"].text
    assert "aria2c" in switches["portal_link_magnet"].text
    assert switches["portal_link_magnet"].text.endswith("Changes apply after a room restart.")
