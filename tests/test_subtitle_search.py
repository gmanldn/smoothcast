"""Focused regression contracts for bounded local subtitle search (#51)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _film(folder: Path, name: str = "Film (2020).mkv") -> Path:
    film = folder / name
    film.write_bytes(b"")
    return film


def _sidecar(folder: Path, name: str, data: bytes = b"1\n00:00:00,000 --> 00:00:01,000\nHi\n"):
    path = folder / name
    path.write_bytes(data)
    return path


def test_matching_rejects_similarly_named_films(tmp_path):
    import subtitle_search
    film = _film(tmp_path)
    exact = _sidecar(tmp_path, "Film (2020).srt")
    tagged = _sidecar(tmp_path, "Film (2020).en.ass")
    _sidecar(tmp_path, "Film (2020) 2.en.srt")
    _sidecar(tmp_path, "Other.en.srt")
    assert subtitle_search.find_subtitle(film, [tmp_path]) == exact
    assert subtitle_search.find_subtitle(film, [tmp_path], ["en"]) == tagged


def test_language_preference_ranks_tagged_sidecars(tmp_path):
    import subtitle_search
    film = _film(tmp_path, "Film.mkv")
    _sidecar(tmp_path, "Film.srt")
    french = _sidecar(tmp_path, "Film.fr.srt")
    english = _sidecar(tmp_path, "Film.en.ass")
    assert subtitle_search.find_subtitle(film, [tmp_path]) == tmp_path / "Film.srt"
    assert subtitle_search.find_subtitle(film, [tmp_path], ["fr"]) == french
    assert subtitle_search.find_subtitle(film, [tmp_path], ["en"]) == english


def test_scan_is_depth_limited_and_skips_symlinks(tmp_path):
    import subtitle_search
    film = _film(tmp_path, "Film.mkv")
    deep = tmp_path / "one" / "two" / "three" / "four"
    deep.mkdir(parents=True)
    found = _sidecar(deep, "Film.en.srt")
    assert subtitle_search.find_subtitle(film, [tmp_path]) == found
    too_deep = tmp_path / "too" / "a" / "b" / "c" / "d" / "e"
    too_deep.mkdir(parents=True)
    _sidecar(too_deep, "Film.en.srt")
    assert subtitle_search.find_subtitle(film, [tmp_path / "too"]) is None
    if os.name != "nt":
        outside = tmp_path / "outside"
        outside.mkdir()
        real = _sidecar(outside, "Film.en.srt")
        links = tmp_path / "links"
        links.mkdir()
        os.symlink(outside, links / "linked", target_is_directory=True)
        os.symlink(real, links / "Film.en.srt")
        assert subtitle_search.find_subtitle(film, [links]) is None


def test_clean_folders_is_bounded_and_rejects_relative_values():
    import subtitle_search
    assert subtitle_search.clean_folders("not-a-list") == []
    absolute = os.path.abspath("/tmp/subtitle-search-a")
    assert subtitle_search.clean_folders(
        [absolute, absolute + "/./", "relative/path", 7, "   "]) == [absolute]
    many = [os.path.abspath(f"/tmp/subtitle-search-{index}")
            for index in range(subtitle_search.MAX_FOLDERS + 3)]
    assert len(subtitle_search.clean_folders(many)) == subtitle_search.MAX_FOLDERS


def test_config_loader_validates_search_folders():
    import config_control
    absolute = os.path.abspath("/tmp/subtitle-search-a")
    cfg = config_control.sanitise_config(
        {"subtitle_search_folders": [absolute, "relative", 7]},
        {"subtitle_search_folders": []},
    )
    assert cfg["subtitle_search_folders"] == [absolute]


def test_auto_resolution_consults_search_folders_before_embedded():
    av = (ROOT / "src" / "cast_av.py").read_text(encoding="utf-8")
    assert "subtitle_search.find_subtitle(" in av
    assert "cfg.get(\"subtitle_search_folders\")" in av
    assert "Found subtitle:" in av
    assert "Found next to video:" not in av


def test_preferences_expose_bounded_search_folders():
    prefs = (ROOT / "src" / "preferences_ui.py").read_text(encoding="utf-8")
    tracks = (ROOT / "src" / "preferences_tracks_ui.py").read_text(encoding="utf-8")
    assert "self._build_subtitle_search(captions)" in prefs
    assert "subtitle_search.clean_folders" in tracks
    assert "select_folder_finish" in tracks
    assert "subtitle_search_row" in tracks