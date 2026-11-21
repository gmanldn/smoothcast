"""Move-stable bookmark identities and bounded config validation."""
from pathlib import Path
import shutil
import sys
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bookmarks
import config_control


class BookmarkTests(unittest.TestCase):
    def test_content_fingerprint_survives_a_move_and_detects_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "first.mkv"
            moved = Path(directory) / "renamed.mkv"
            source.write_bytes(b"large media bytes" * 100_000)
            original = bookmarks.fingerprint(source)
            shutil.move(source, moved)
            self.assertEqual(bookmarks.fingerprint(moved), original)
            moved.write_bytes(b"different media")
            self.assertNotEqual(bookmarks.fingerprint(moved), original)

    def test_fingerprint_rejects_symlinks_and_non_files(self):
        if os.name == "nt" or not hasattr(os, "symlink"):
            self.skipTest("symlink creation is not portable in this environment")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.mkv"
            alias = Path(directory) / "alias.mkv"
            target.write_bytes(b"video")
            alias.symlink_to(target)
            with self.assertRaises(bookmarks.BookmarkError):
                bookmarks.fingerprint(alias)
            with self.assertRaises(bookmarks.BookmarkError):
                bookmarks.fingerprint(directory)

    def test_records_are_bounded_validated_and_do_not_keep_paths(self):
        digest = "a" * 64
        saved = bookmarks.add([], digest, " Favourite scene ", "movie.mkv", 12.5, 20)
        self.assertEqual(saved[0], {
            "fingerprint": digest, "name": "Favourite scene", "media": "movie.mkv",
            "position": 12.5, "created": 20.0,
        })
        self.assertNotIn("path", saved[0])
        dirty = [
            *saved,
            {**saved[0], "fingerprint": "../secret"},
            {**saved[0], "position": float("nan")},
            {**saved[0], "name": "bad\nname"},
            object(),
        ]
        self.assertEqual(bookmarks.clean(dirty), [saved[0]])
        capped = bookmarks.clean([saved[0]] * (bookmarks.LIMIT + 10))
        self.assertEqual(len(capped), bookmarks.LIMIT)
        self.assertEqual(bookmarks.at(capped, -1), None)

    def test_config_sanitizer_keeps_valid_markers_and_discards_bad_records(self):
        digest = "b" * 64
        valid = {"fingerprint": digest, "name": "Scene", "media": "film.mkv",
                 "position": 5, "created": 10}
        defaults = {"bookmarks": []}
        config = config_control.sanitise_config({"bookmarks": [valid, {"name": "bad"}]}, defaults)
        self.assertEqual(config["bookmarks"], [{
            "fingerprint": digest, "name": "Scene", "media": "film.mkv",
            "position": 5.0, "created": 10.0,
        }])
        self.assertEqual(config_control.sanitise_config({"bookmarks": None}, defaults), defaults)


if __name__ == "__main__":
    unittest.main()
