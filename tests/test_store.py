

def test_corrupt_file_is_quarantined_not_reread(tmp_path):
    from store import Store
    path = tmp_path / "x.json"
    path.write_text("{not json")
    assert Store(path).read({"a": 1}) == {"a": 1}
    assert not path.exists() and (tmp_path / "x.json.corrupt").read_text() == "{not json"
    assert Store(path).write({"b": 2}) and Store(path).read() == {"b": 2}
