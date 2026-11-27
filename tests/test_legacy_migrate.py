import legacy_migrate


def test_copies_keeps_source_and_is_idempotent(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    (old / "sub").mkdir(parents=True)
    (old / "a.json").write_text("1")
    (old / "sub" / "b.json").write_text("2")
    assert sorted(legacy_migrate.migrate(old, new)) == ["a.json", "sub/b.json"]
    assert (old / "a.json").read_text() == "1"
    assert (new / "sub" / "b.json").read_text() == "2"
    assert legacy_migrate.migrate(old, new) == []


def test_never_overwrites_existing_new_file(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "a.json").write_text("old")
    (new / "a.json").write_text("new")
    legacy_migrate.migrate(old, new)
    assert (new / "a.json").read_text() == "new"


def test_missing_or_same_dir_is_noop(tmp_path):
    assert legacy_migrate.migrate(tmp_path / "none", tmp_path / "x") == []
    assert legacy_migrate.migrate(tmp_path, tmp_path) == []
