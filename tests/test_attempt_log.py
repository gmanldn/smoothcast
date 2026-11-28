import json

import attempt_log as al


def test_each_attempt_has_its_own_folder_and_retries_do_not_overwrite(tmp_path):
    a = al.begin(tmp_path, argv=["ffmpeg", "-i", "x"], plan_reason="software: no hw")
    a.write("ffmpeg.log", "first failure")
    a.finish("failed", "exit 1")
    b = al.begin(tmp_path, argv=["ffmpeg"], plan_reason="720p")
    b.write("ffmpeg.log", "second")
    assert a.folder != b.folder
    assert (a.folder / "ffmpeg.log").read_text() == "first failure"
    assert json.loads((a.folder / "outcome.json").read_text())["outcome"] == "failed"
    assert (a.folder / "plan.txt").read_text() == "software: no hw"


def test_only_the_newest_attempts_are_kept(tmp_path):
    for _ in range(7):
        al.begin(tmp_path, keep=3)
    assert len(list((tmp_path / "attempts").iterdir())) == 3


def test_files_are_size_capped_keeping_the_tail(tmp_path):
    a = al.begin(tmp_path)
    a.write("ffmpeg.log", "x" * 200_000 + "THE END")
    data = (a.folder / "ffmpeg.log").read_text()
    assert len(data) == al.MAX_FILE and data.endswith("THE END")


def test_redaction_strips_paths_and_secrets():
    raw = "open /home/alice/Films/Secret Movie.mkv failed token=abc123 csrf: xyz C:\\Users\\bob\\v.mp4"
    out = al.redact(raw)
    assert "alice" not in out and "abc123" not in out and "xyz" not in out and "bob" not in out
    assert "failed" in out


def test_bundle_is_redacted_and_never_raises_on_missing_root(tmp_path):
    a = al.begin(tmp_path, argv=["ffmpeg", "-i", "/home/alice/a.mkv"])
    a.write("ffmpeg.log", "error in /home/alice/a.mkv")
    text = json.dumps(al.bundle(tmp_path))
    assert "alice" not in text
    assert al.bundle(tmp_path / "nope") == {}


def test_attempt_defaults_to_the_active_command_trace_id(tmp_path):
    import command_trace
    with command_trace.scope("cli", "cast"):
        trace_id = command_trace.current_id()
        a = al.begin(tmp_path)
    assert trace_id and trace_id in a.folder.name


def test_unsafe_correlation_id_cannot_escape_the_attempts_folder(tmp_path):
    a = al.begin(tmp_path, correlation_id="../../etc/x y")
    assert a.folder.parent == tmp_path / "attempts" and "/" not in a.folder.name
