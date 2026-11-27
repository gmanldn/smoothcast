"""Plain-file export (#435): order-preserving playlists, no secrets, headless."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import exporters  # noqa: E402

CONFIG = {
    "quality": "1080p",
    "house_pin_enabled": True,
    "control_api_token": "abc123",
    "mesh": {"node_secret": "s3cret", "name": "Lounge"},
    "window_width": 1200,
    "positions": {"/m/a.mkv": 61.5, "/m/bad.mkv": "x"},
    "watch_history": [],
}


def queue(tmp_path: Path) -> list[str]:
    names = ["Zeta film.mkv", "alpha & beta.mp4", "Ünïcode track.flac", "space name.mkv"]
    return [str(tmp_path / "media" / n) for n in names]


def test_export_writes_every_file_and_queue_round_trips_in_order(tmp_path):
    items = queue(tmp_path)
    written = exporters.export(tmp_path / "out", config=CONFIG, queue=items,
                               names={items[0]: "Zeta"})
    assert [p.name for p in written] == list(exporters.FILES)
    assert exporters.read_xspf(tmp_path / "out/queue.xspf") == items
    assert exporters.read_m3u8(tmp_path / "out/queue.m3u8") == items
    m3u = (tmp_path / "out/queue.m3u8").read_text(encoding="utf-8")
    assert m3u.startswith("#EXTM3U\n#EXTINF:-1,Zeta\n")
    rooms = json.loads((tmp_path / "out/rooms.json").read_text(encoding="utf-8"))
    assert rooms["rooms"][0]["queue"] == items


def test_m3u8_round_trip_through_the_desktop_playlist_loader(tmp_path):
    import playlist_control
    items = queue(tmp_path)
    for item in items:
        Path(item).parent.mkdir(parents=True, exist_ok=True)
        Path(item).write_bytes(b"x")
    exporters.export(tmp_path / "out", config={}, queue=items)
    loaded, skipped = playlist_control.load_playlist(tmp_path / "out/queue.m3u8")
    assert loaded == [str(Path(i).resolve()) for i in items] and skipped == 0


def test_preferences_never_contain_secrets_watch_state_or_geometry(tmp_path):
    exporters.export(tmp_path, config=CONFIG, queue=[])
    prefs = json.loads((tmp_path / "preferences.json").read_text(encoding="utf-8"))
    assert prefs == {"quality": "1080p", "house_pin_enabled": True, "mesh": {"name": "Lounge"}}
    text = "".join((tmp_path / name).read_text(encoding="utf-8") for name in exporters.FILES)
    assert "abc123" not in text and "s3cret" not in text


def test_history_keeps_numeric_positions_only(tmp_path):
    exporters.export(tmp_path, config=CONFIG, queue=[])
    history = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert history["positions"] == {"/m/a.mkv": 61.5}
    assert history["watch_history"] == []


def test_line_breaks_in_a_path_cannot_inject_playlist_entries(tmp_path):
    with pytest.raises(exporters.ExportError):
        exporters.export(tmp_path, config={}, queue=["/m/a.mkv\n/etc/passwd"])
    assert not any(tmp_path.iterdir())


def test_xspf_reader_refuses_entity_declarations(tmp_path):
    bad = tmp_path / "bad.xspf"
    bad.write_text('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><playlist/>')
    with pytest.raises(exporters.ExportError):
        exporters.read_xspf(bad)


def test_cli_exports_from_the_user_config_without_gtk(tmp_path, monkeypatch, capsys):
    import room_checkpoint
    config_dir = tmp_path / "xdg/cast-control"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    item = tmp_path / "film.mkv"
    item.write_bytes(b"x")
    room_checkpoint.write_checkpoint(config_dir / "room-checkpoint.json", [str(item)])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert exporters.main(["--to", str(tmp_path / "out")]) == 0
    assert "Exported 1 queued item(s)" in capsys.readouterr().out
    assert exporters.read_m3u8(tmp_path / "out/queue.m3u8") == [str(item)]


def test_exporter_never_imports_gtk():
    import subprocess
    src = Path(__file__).resolve().parents[1] / "src"
    code = f"import sys; sys.path.insert(0, {str(src)!r}); import exporters; assert 'gi' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)
