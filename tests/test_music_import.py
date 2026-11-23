"""Headless regressions for bounded media/folder import discovery."""
from __future__ import annotations

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import music_import


def test_discovers_nested_supported_media_in_natural_order_and_skips_others(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    for name in ("track10.flac", "track2.mp3", "notes.txt"):
        (album / name).write_text("fixture")
    nested = album / "disc2"
    nested.mkdir()
    (nested / "track1.m4a").write_text("fixture")

    result = music_import.discover([album])

    assert result.paths == tuple(map(str, (
        album / "track2.mp3", album / "track10.flac", nested / "track1.m4a",
    )))
    assert result.skipped == 1
    assert not result.truncated and not result.cancelled


def test_explicit_files_keep_selection_order_and_deduplicate(tmp_path):
    paths = [tmp_path / name for name in ("song10.mp3", "song2.mp3")]
    for path in paths:
        path.touch()

    result = music_import.discover(
        [paths[0], paths[1], paths[0]], natural_sort=False,
    )

    assert result.paths == (str(paths[0]), str(paths[1]))
    assert result.skipped == 0


def test_never_follows_symlinked_directory_or_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    song = outside / "song.mp3"
    song.touch()
    root = tmp_path / "chosen"
    root.mkdir()
    try:
        (root / "linked-dir").symlink_to(outside, target_is_directory=True)
        (root / "linked-file.mp3").symlink_to(song)
    except OSError:
        return

    result = music_import.discover([root])

    assert result.paths == ()
    assert result.skipped == 2


def test_caps_returned_items_and_reports_truncation(tmp_path):
    for name in ("one.mp3", "two.mp3", "three.mp3"):
        (tmp_path / name).touch()
    updates = []

    result = music_import.discover([tmp_path], max_items=2, progress=updates.append)

    assert len(result.paths) == 2
    assert result.truncated
    assert updates and updates[-1] == result.visited


def test_caps_total_directory_entries(tmp_path):
    for name in ("one.txt", "two.txt", "three.txt"):
        (tmp_path / name).touch()

    result = music_import.discover([tmp_path], max_entries=2)

    assert result.visited == 2
    assert result.truncated
    assert not result.paths


def test_cancellation_stops_directory_walk(tmp_path):
    for index in range(music_import.PROGRESS_INTERVAL * 3):
        (tmp_path / f"track{index}.mp3").touch()
    cancel = threading.Event()
    updates = []

    def stop_after_first_batch(count):
        updates.append(count)
        cancel.set()

    result = music_import.discover(
        [tmp_path], cancel=cancel, progress=stop_after_first_batch,
    )

    assert result.cancelled
    assert result.visited <= music_import.PROGRESS_INTERVAL
    assert updates


def test_missing_paths_and_unsupported_directories_are_counted(tmp_path):
    result = music_import.discover([tmp_path / "gone.mp3", tmp_path / "notes.txt"])

    assert result.paths == ()
    assert result.skipped == 2
    assert result.visited == 2


def test_embedded_album_tags_order_by_disc_then_track():
    paths = ["album/track10.flac", "album/track2.flac", "album/track1-disc2.flac"]
    metadata = {
        paths[0]: SimpleNamespace(artist="Artist", album="Album", disc_number=1, track_number=10),
        paths[1]: SimpleNamespace(artist="Artist", album="Album", disc_number=1, track_number=2),
        paths[2]: SimpleNamespace(artist="Artist", album="Album", disc_number=2, track_number=1),
    }

    assert music_import.order_tracks(paths, metadata) == [paths[1], paths[0], paths[2]]


def test_incomplete_album_tags_fall_back_to_natural_filename_order():
    paths = ["album/track10.mp3", "album/track2.mp3"]
    metadata = {
        paths[0]: SimpleNamespace(artist="Artist", album="Album", track_number=10),
        paths[1]: SimpleNamespace(artist="Artist", album="Album", track_number=0),
    }

    assert music_import.order_tracks(paths, metadata) == [paths[1], paths[0]]
