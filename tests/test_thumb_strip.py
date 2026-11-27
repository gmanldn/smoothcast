import thumb_strip as ts


def test_interval_caps_frame_count():
    assert ts.interval_for(60) == ts.MIN_INTERVAL
    assert ts.interval_for(7200) * ts.MAX_THUMBS >= 7200
    assert ts.interval_for(float("nan")) == ts.MIN_INTERVAL


def test_nearest_index_clamps_and_survives_bad_input():
    assert ts.nearest_index(-3, 10, 5) == 0
    assert ts.nearest_index(999, 10, 5) == 4
    assert ts.nearest_index(float("inf"), 10, 5) == 0
    assert ts.nearest_index(25, 10, 5) == 2
    assert ts.nearest_index(5, 10, 0) == 0


def test_step_position_clamps_to_media():
    assert ts.step_position(0.0, -1, 25, 10) == 0.0
    assert ts.step_position(10.0, 1, 25, 10) == 10.0
    assert abs(ts.step_position(1.0, 1, 25, 10) - 1.04) < 1e-9
    assert abs(ts.step_position(1.0, 1, 0, 10) - 1.04) < 1e-9


def test_build_strip_caches_and_reuses(tmp_path, monkeypatch):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"x")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = cmd[-1].rsplit("/", 1)[0]
        for i in (1, 2, 3):
            open(f"{out}/t{i:04d}.jpg", "wb").write(b"\xff\xd8")

    monkeypatch.setattr(ts.media_tools, "resolve_media_tool", lambda n: n)
    monkeypatch.setattr(ts.subprocess, "run", fake_run)
    first = ts.build_strip(src, 30, tmp_path / "cache")
    second = ts.build_strip(src, 30, tmp_path / "cache")
    assert len(first) == 3 and first == second and len(calls) == 1


def test_build_strip_failure_leaves_no_cache(tmp_path, monkeypatch):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"x")
    monkeypatch.setattr(ts.media_tools, "resolve_media_tool", lambda n: n)

    def boom(cmd, **kw):
        raise ts.subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(ts.subprocess, "run", boom)
    assert ts.build_strip(src, 30, tmp_path / "cache") == []
    assert list((tmp_path / "cache" / "thumbs").iterdir()) == []
