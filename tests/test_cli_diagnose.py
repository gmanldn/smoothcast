"""`smoothcast diagnose` writes a redacted bundle and sends nothing (#698)."""
import json
import os
import stat

import attempt_log
import cli_control
import paths


def test_diagnose_writes_private_redacted_bundle(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "cache"
    monkeypatch.setattr(paths, "cache_dir", lambda home=None: cache)
    a = attempt_log.begin(cache, argv=["ffmpeg", "-i", "/home/sam/Movies/secret.mkv"], plan_reason="software", correlation_id="cid1")
    a.write("stderr.txt", "opened /home/sam/Movies/secret.mkv token=abc123def456ghi789")
    out = tmp_path / "bundle.json"
    code = cli_control.main(["diagnose", "--out", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] and payload["path"] == str(out)
    text = out.read_text()
    assert "secret.mkv" not in text and "abc123def456ghi789" not in text
    assert json.loads(text)["attempts"]
    if os.name != "nt":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_diagnose_unwritable_destination_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "cache_dir", lambda home=None: tmp_path)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    code = cli_control.main(["diagnose", "--out", str(blocker / "b.json"), "--json"])
    assert code == cli_control.EXIT_FAILED
    assert json.loads(capsys.readouterr().out)["ok"] is False
