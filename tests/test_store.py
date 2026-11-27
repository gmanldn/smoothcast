

def test_corrupt_file_is_quarantined_not_reread(tmp_path):
    from store import Store
    path = tmp_path / "x.json"
    path.write_text("{not json")
    assert Store(path).read({"a": 1}) == {"a": 1}
    assert not path.exists() and (tmp_path / "x.json.corrupt").read_text() == "{not json"
    assert Store(path).write({"b": 2}) and Store(path).read() == {"b": 2}


def test_failed_write_reports_a_typed_reason(tmp_path):
    import errno
    from store import Store, classify_error
    assert classify_error(OSError(errno.ENOSPC, "x")) == "disk_full"
    assert classify_error(OSError(errno.EACCES, "x")) == "permission_denied"
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = Store(blocker / "sub" / "x.json")
    assert store.write({"a": 1}) is False and store.last_error in ("io_error", "permission_denied")
    ok = Store(tmp_path / "ok.json")
    assert ok.write({"a": 1}) and ok.last_error is None


def test_quarantine_is_recorded_for_a_startup_notice(tmp_path):
    import store
    store.QUARANTINED.clear()
    path = tmp_path / "y.json"
    path.write_text("[1")
    store.Store(path).read()
    assert store.QUARANTINED == ["y.json"]
    store.QUARANTINED.clear()
