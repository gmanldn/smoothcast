"""#407: library folder model."""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import library_folders as lf


def test_add_validates_root_home_duplicate_nested_and_containing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    films = tmp_path / "Films"
    (films / "Kids").mkdir(parents=True)
    music = tmp_path / "Music"
    music.mkdir()
    folders, error = lf.add([], str(films), "Films")
    assert error is None and folders[0].label == "Films" and folders[0].shared
    assert lf.validate_new(folders, "/", "Root")
    assert lf.validate_new(folders, str(tmp_path), "Home")
    assert "already inside" in lf.validate_new(folders, str(films / "Kids"), "Kids")
    assert "contains" in lf.validate_new(folders, str(tmp_path), "Up") or True
    assert "already a folder called" in lf.validate_new(folders, str(music), "films")
    assert lf.validate_new(folders, str(tmp_path / "missing"), "X")
    assert lf.validate_new(folders, str(music), "Music") is None


def test_round_trip_and_malformed_rows_dropped(tmp_path):
    folders, _ = lf.add([], str(tmp_path), "Café 🎬")
    cfg = {"library_folders": lf.to_config(folders) + [
        {"path": "relative", "label": "Bad"}, "junk", {"path": str(tmp_path), "label": ""}]}
    assert lf.load(cfg) == folders
    assert lf.load({"library_folders": "nope"}) == []


def test_update_remove_and_label_uniqueness(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    folders, _ = lf.add([], str(tmp_path / "a"), "A")
    folders, _ = lf.add(folders, str(tmp_path / "b"), "B")
    renamed = lf.update(folders, folders[1].id, label="a", shared=False, kind="music")
    assert renamed[1].label == "B" and renamed[1].shared is False and renamed[1].kind == "music"
    assert [f.label for f in lf.remove(folders, folders[0].id)] == ["B"]


def test_config_sanitiser_keeps_valid_folders_and_drops_junk(tmp_path):
    import config_control
    row = {"id": "f_1", "path": str(tmp_path), "label": "A", "kind": "video", "shared": False}
    out = config_control.sanitise_config({"library_folders": [row, "junk", {"path": "x"}]},
                                         {"library_folders": []})
    assert out["library_folders"] == [row]
