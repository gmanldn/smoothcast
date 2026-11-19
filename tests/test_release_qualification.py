"""Pure, GTK-free qualification state and evidence integrity regressions."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "release_qualification.py"
spec = importlib.util.spec_from_file_location("release_qualification", SCRIPT)
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
SHA = "a" * 40
OTHER_SHA = "b" * 40
DATE = "2026-11-19T10:00:00Z"
URL = "https://github.com/gmanldn/smoothcast/actions/runs/123"


def manifest():
    return {"schema_version": 1, "releases": {}}


def add_release(data):
    qualification.init_release(data, "1.2.3", SHA)
    return data["releases"]["1.2.3"]


def passing(check, *, commit=SHA):
    entry = {"status": "pass", "evidence": URL,
             "checked_at": DATE, "commit": commit}
    if qualification.CHECKS[check][3]:
        entry.update(device_model="Chromecast 3", notes="Play, seek and stop verified")
    return entry


def test_no_release_record_is_not_qualified():
    state = qualification.summary(manifest(), "1.2.3")
    assert state["ready"] is False
    assert state["pending_required"] > 0
    assert "NOT QUALIFIED" in qualification.markdown(state)
    assert "not recorded" in qualification.markdown(state)


def test_init_requires_explicit_revision_and_never_clobbers_evidence():
    data = manifest()
    add_release(data)
    assert data["releases"]["1.2.3"]["checks"] == {}
    with pytest.raises(qualification.QualificationError, match="already exists"):
        qualification.init_release(data, "1.2.3", OTHER_SHA)
    with pytest.raises(qualification.QualificationError, match="40-char"):
        qualification.init_release(data, "1.2.4", "short")


def test_all_required_passes_qualify_but_optional_devices_remain_pending():
    data = manifest()
    release = add_release(data)
    release["checks"] = {k: passing(k) for k, v in qualification.CHECKS.items() if v[2]}
    state = qualification.summary(data, "1.2.3")
    assert state["ready"] is True
    assert state["statuses"]["dlna-lg"] == "pending"
    assert "QUALIFIED (required gates)" in qualification.markdown(state)
    assert "PENDING" in qualification.markdown(state)


def test_old_evidence_never_qualifies_current_commit():
    data = manifest()
    release = add_release(data)
    release["checks"] = {k: passing(k) for k, v in qualification.CHECKS.items() if v[2]}
    release["checks"]["portable-python-310"]["commit"] = OTHER_SHA
    qualification.validate_entry("1.2.3", release)
    state = qualification.summary(data, "1.2.3")
    assert not state["ready"]
    assert state["statuses"]["portable-python-310"] == "stale"
    assert "stale commit" in qualification.markdown(state)


def test_failed_optional_device_and_unresolved_known_failure_block_release():
    data = manifest()
    release = add_release(data)
    release["checks"] = {k: passing(k) for k, v in qualification.CHECKS.items() if v[2]}
    failed = passing("dlna-lg")
    failed.update(status="fail", device_model="LG OLED", notes="Seek timed out")
    release["checks"]["dlna-lg"] = failed
    state = qualification.summary(data, "1.2.3")
    assert state["blocked"] and not state["ready"]
    release["checks"].pop("dlna-lg")
    release["known_failures"] = [{"summary": "Regression in cast resume", "status": "open",
                                  "issue": "https://github.com/gmanldn/smoothcast/issues/70"}]
    state = qualification.summary(data, "1.2.3")
    assert state["blocked"] and not state["ready"]
    assert "Regression in cast resume" in qualification.markdown(state)


@pytest.mark.parametrize("change,error", [
    (lambda e: e["checks"].update(typo={"status": "pending"}), "unknown check"),
    (lambda e: e["checks"].update({"setup-linux": {"status": "pass"}}), "dated HTTPS"),
    (lambda e: e["checks"].update({"setup-linux": {"status": "unsupported", "notes": "skip"}}), "mandatory"),
    (lambda e: e["checks"].update({"roku": {"status": "unsupported"}}), "requires a reason"),
    (lambda e: e["checks"].update({"cast-chromecast": passing("setup-linux")}), "device model"),
    (lambda e: e.update(known_failures=[{"summary": "Oops", "status": "open", "issue": "file:///etc/passwd"}]), "HTTPS issue"),
])
def test_invalid_evidence_is_rejected(change, error):
    data = manifest()
    entry = add_release(data)
    change(entry)
    with pytest.raises(qualification.QualificationError, match=error):
        qualification.validate_entry("1.2.3", entry)


def test_manifest_duplicate_keys_are_not_silently_accepted(tmp_path):
    path = tmp_path / "qualification.json"
    path.write_text('{"schema_version":1,"releases":{},"releases":{}}')
    with pytest.raises(qualification.QualificationError, match="Duplicate JSON key"):
        qualification.load_manifest(path)


def test_headless_cli_init_and_strict_roundtrip(tmp_path, capsys):
    path = tmp_path / "qualification.json"
    path.write_text(json.dumps(manifest()))
    args = ["--manifest", str(path), "--release", "1.2.3"]
    assert qualification.main(args + ["--init", "--sha", SHA]) == 0
    assert qualification.main(args + ["--strict"]) == 1
    assert not qualification.summary(qualification.load_manifest(path), "1.2.3")["ready"]
    assert qualification.main(args + ["--init", "--sha", SHA]) == 2
    assert "already exists" in capsys.readouterr().err


def test_canonical_version_is_read_without_importing_gtk(tmp_path):
    version = tmp_path / "version.py"
    version.write_text('MAJOR = 1\nMINOR = 2\nPATCH = 3\nimport gi\nraise RuntimeError("must not execute")\n')
    assert qualification.canonical_version(version) == "1.2.3"
    assert qualification.canonical_version() == qualification.canonical_version(
        SCRIPT.parents[2] / "src" / "version.py")


def test_documented_manifest_is_valid_and_current_release_report_is_honest():
    data = qualification.load_manifest(SCRIPT.parents[2] / "docs" / "release_qualification.json")
    state = qualification.summary(data, qualification.canonical_version())
    assert state["ready"] is False


def test_report_output_does_not_overwrite_manifest(tmp_path, capsys):
    path = tmp_path / "data.json"
    original = json.dumps(manifest())
    path.write_text(original)
    assert qualification.main(["--manifest", str(path), "--release", "1.2.3", "--output", str(path)]) == 2
    assert path.read_text() == original
    assert "must not overwrite" in capsys.readouterr().err
