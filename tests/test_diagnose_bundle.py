import json

import attempt_log
import diagnose_bundle as db


def test_bundle_contains_versions_and_attempts_without_paths_or_tokens(tmp_path):
    a = attempt_log.begin(tmp_path, argv=["ffmpeg", "-i", "/home/alice/Films/x.mkv"], plan_reason="software")
    a.write("ffmpeg.log", "failed reading /home/alice/Films/x.mkv token=SECRET1")
    a.finish("failed", "exit 1")
    out = db.write_bundle(tmp_path, tmp_path / "out" / "diag.json", app_version="2.3.0",
                          capabilities={"hw": "vaapi at /dev/dri/renderD129 pin=123456"})
    text = out.read_text()
    data = json.loads(text)
    assert data["app_version"] == "2.3.0" and len(data["attempts"]) == 1
    for secret in ("alice", "SECRET1", "123456"):
        assert secret not in text


def test_empty_root_still_writes_a_valid_bundle(tmp_path):
    out = db.write_bundle(tmp_path / "none", tmp_path / "d.json")
    assert json.loads(out.read_text())["attempts"] == {}
