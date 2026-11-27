"""Jellyfin/Plex/Kodi watch-state import (#435): dry run never writes, accurate matching."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import importers  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "import"


def library(tmp_path: Path, names: list[str]) -> Path:
    root = tmp_path / "media"
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return root


LOCAL = ["Films/Arrival (2016)/Arrival.2016.1080p.BluRay.x264.mkv", "Films/Heat.1995.mkv",
         "TV/Its Always Sunny in Philadelphia/Season 02/Its.Always.Sunny.in.Philadelphia.S02E03.mkv",
         "TV/Breaking Bad/Season 1/Breaking.Bad.S01E01.720p.mkv"]


def test_jellyfin_fixture_parses_ticks_and_watched_state():
    records = importers.parse_jellyfin(FIXTURES / "jellyfin_items.json")
    assert [r.title for r in records][:2] == ["Arrival", "Heat"]
    assert records[0].position == 1800.0 and records[0].duration == 6960.0
    assert records[1].watched and records[2].kind == "episode" and records[2].season == 2
    assert all(r.title != "Folder" for r in records)


def test_plex_fixture_parses_milliseconds_and_episodes():
    records = importers.parse_plex(FIXTURES / "plex_library.csv")
    assert records[0].position == 1800.0 and not records[0].watched
    assert records[1].watched and records[2].kind == "episode" and records[2].show == "Breaking Bad"


def test_matching_by_filename_title_year_and_episode(tmp_path):
    lib = importers.Library(importers.scan([library(tmp_path, LOCAL)]))
    report = importers.match_all(importers.parse_jellyfin(FIXTURES / "jellyfin_items.json"), lib)
    matched = {r.title: (Path(p).name, how) for r, p, how in report.matched}
    assert matched["Arrival"][0].startswith("Arrival.2016") and matched["Arrival"][1] == "title"
    assert matched["Heat"] == ("Heat.1995.mkv", "filename")  # Windows path, same file name
    assert matched["The Gang Goes Jihad"][0].endswith("S02E03.mkv")
    assert [r.title for r in report.unmatched] == ["Missing Here"]  # Unwatched items are skipped


def test_matching_accuracy_on_clean_names_is_at_least_95_percent(tmp_path):
    films = [(f"Film Number {n}", 1980 + n) for n in range(30)]
    episodes = [("Show Alpha", s, e) for s in (1, 2) for e in range(1, 11)]
    names = [f"Films/{t} ({y}).mkv" for t, y in films]
    names += [f"TV/{s}/Season {n}/{s} S{n:02d}E{e:02d}.mkv" for s, n, e in episodes]
    lib = importers.Library(importers.scan([library(tmp_path, names)]))
    records = [importers.Record(title=t, year=y, watched=True) for t, y in films]
    records += [importers.Record(title="x", kind="episode", show=s, season=n, episode=e, watched=True)
                for s, n, e in episodes]
    report = importers.match_all(records, lib)
    correct = 0
    for record, path, _how in report.matched:
        if record.kind == "movie":
            correct += Path(path).stem == f"{record.title} ({record.year})"
        else:
            correct += Path(path).stem.endswith(f"S{record.season:02d}E{record.episode:02d}")
    assert correct / len(records) >= 0.95


def test_duplicate_candidates_are_reported_ambiguous_not_guessed(tmp_path):
    lib = importers.Library(importers.scan([library(tmp_path, ["a/Heat (1995).mkv", "b/Heat (1995).mp4"])]))
    report = importers.match_all([importers.Record(title="Heat", year=1995, watched=True)], lib)
    assert not report.matched and len(report.ambiguous[0][1]) == 2


def test_dry_run_never_writes(tmp_path, monkeypatch, capsys):
    xdg = tmp_path / "xdg"
    (xdg / "cast-control").mkdir(parents=True)
    config = xdg / "cast-control/config.json"
    config.write_text(json.dumps({"quality": "auto"}), encoding="utf-8")
    before = config.read_bytes(), config.stat().st_mtime_ns
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    media = library(tmp_path, LOCAL)
    assert importers.main(["jellyfin", str(FIXTURES / "jellyfin_items.json"), "--media", str(media)]) == 0
    assert "3 matched" in capsys.readouterr().out
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
    assert sorted(p.name for p in config.parent.iterdir()) == ["config.json"]


def test_apply_merges_only_watch_state_into_settings(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    (xdg / "cast-control").mkdir(parents=True)
    config = xdg / "cast-control/config.json"
    config.write_text(json.dumps({"quality": "720p", "custom_key": [1, 2]}), encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    media = library(tmp_path, LOCAL)
    args = ["plex", str(FIXTURES / "plex_library.csv"), "--media", str(media), "--apply"]
    assert importers.main(args) == 0
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["quality"] == "720p" and saved["custom_key"] == [1, 2]
    arrival = str(media / LOCAL[0])
    assert saved["positions"] == {arrival: 1800.0}
    events = {(Path(e["path"]).name, e["event"]) for e in saved["watch_history"]}
    assert ("Heat.1995.mkv", "completed") in events
    assert ("Breaking.Bad.S01E01.720p.mkv", "completed") in events


def make_kodi(path: Path, version: int = 131) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(f"""
        CREATE TABLE version (idVersion INTEGER, iCompressCount INTEGER);
        INSERT INTO version VALUES ({version}, 0);
        CREATE TABLE path (idPath INTEGER PRIMARY KEY, strPath TEXT);
        CREATE TABLE files (idFile INTEGER PRIMARY KEY, idPath INTEGER, strFilename TEXT,
                            playCount INTEGER, lastPlayed TEXT);
        CREATE TABLE bookmark (idBookmark INTEGER PRIMARY KEY, idFile INTEGER, timeInSeconds REAL,
                               totalTimeInSeconds REAL, type INTEGER);
        CREATE TABLE movie (idMovie INTEGER PRIMARY KEY, idFile INTEGER, c00 TEXT, premiered TEXT);
        CREATE TABLE tvshow (idShow INTEGER PRIMARY KEY, c00 TEXT);
        CREATE TABLE episode (idEpisode INTEGER PRIMARY KEY, idFile INTEGER, c00 TEXT, c12 TEXT,
                              c13 TEXT, idShow INTEGER);
        INSERT INTO path VALUES (1, 'smb://nas/films/'), (2, 'smb://nas/tv/Breaking Bad/');
        INSERT INTO files VALUES (1, 1, 'Arrival.2016.1080p.BluRay.x264.mkv', NULL, NULL),
                                 (2, 2, 'Breaking.Bad.S01E01.720p.mkv', 1, '2024-01-01');
        INSERT INTO bookmark VALUES (1, 1, 1800, 6960, 1);
        INSERT INTO movie VALUES (1, 1, 'Arrival', '2016-11-11');
        INSERT INTO tvshow VALUES (1, 'Breaking Bad');
        INSERT INTO episode VALUES (1, 2, 'Pilot', '1', '1', 1);
    """)
    conn.commit()
    conn.close()


def test_kodi_database_copy_is_read_only_and_matched(tmp_path):
    db = tmp_path / "MyVideos131.db"
    make_kodi(db)
    before = db.read_bytes()
    records = importers.parse_kodi(db)
    assert db.read_bytes() == before
    lib = importers.Library(importers.scan([library(tmp_path, LOCAL)]))
    report = importers.match_all(records, lib)
    assert {(r.title, how) for r, _p, how in report.matched} == {("Arrival", "filename"), ("Pilot", "filename")}
    arrival = next(r for r in records if r.title == "Arrival")
    assert arrival.position == 1800 and arrival.year == 2016 and not arrival.watched


@pytest.mark.parametrize("make, source, message", [
    (lambda p: p.write_text('{"Version": 9}'), "jellyfin", "Unsupported Jellyfin export"),
    (lambda p: p.write_text("Foo\nx\n"), "plex", "no Title column"),
    (lambda p: make_kodi(p, version=60), "kodi", "Unsupported Kodi database version 60"),
    (lambda p: sqlite3.connect(p).execute("CREATE TABLE t (a)").connection.commit(), "kodi",
     "Not a Kodi video database"),
])
def test_unknown_formats_fail_with_a_clear_error(tmp_path, make, source, message):
    path = tmp_path / "export"
    make(path)
    with pytest.raises(importers.ImportError_, match=message):
        importers.PARSERS[source](path)
