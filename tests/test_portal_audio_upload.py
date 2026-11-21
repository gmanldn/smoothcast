"""Authenticated phone audio uploads validate before joining shared Up Next."""
from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import streamer
import portal_uploads


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class PortalAudioUploadTests(unittest.TestCase):
    def make_audio(self, path: Path) -> None:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=0.5", "-metadata", "title=Guest track",
             "-metadata", "artist=Guest artist", "-c:a", "libmp3lame", "-y", str(path)],
            check=True, capture_output=True, timeout=20,
        )

    def manager(self, root: Path) -> portal_uploads.UploadManager:
        return portal_uploads.UploadManager(
            root, disk_usage=lambda _path: SimpleNamespace(free=2**40),
            early_cast_min_bytes=1,
        )

    def append_file(self, uploads, owner: str, upload_id: str, path: Path) -> None:
        data = path.read_bytes()
        uploads.append(owner, upload_id, f"bytes 0-{len(data) - 1}/{len(data)}",
                       len(data), BytesIO(data))

    def test_audio_is_queued_and_probe_validated_before_finalize(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "track.mp3"
            self.make_audio(source)
            uploads = self.manager(root / "uploads")
            created = uploads.create("guest", "track.mp3", source.stat().st_size,
                                     queue_only=False)
            self.assertTrue(uploads.is_queue_only("guest", created["id"]))
            self.assertTrue(uploads.is_audio_only("guest", created["id"]))

            self.append_file(uploads, "guest", created["id"], source)
            self.assertFalse(uploads.status("guest", created["id"])["ready_to_cast"])
            path, name, dispatch = uploads.finalize("guest", created["id"])
            media = streamer.ffprobe(path)

            self.assertEqual(name, "track.mp3")
            self.assertTrue(dispatch)
            self.assertTrue(media.is_audio_only)
            self.assertEqual(media.title, "Guest track")
            replayed_path, replayed_name, replay_dispatch = uploads.finalize(
                "guest", created["id"],
            )
            self.assertEqual((replayed_path, replayed_name, replay_dispatch),
                             (path, name, False))
            uploads.close()

    def test_corrupt_audio_is_removed_and_never_dispatched(self):
        with tempfile.TemporaryDirectory() as folder:
            uploads = self.manager(Path(folder) / "uploads")
            invalid = b"not audio"
            created = uploads.create("guest", "not-a-song.mp3", len(invalid))
            uploads.append("guest", created["id"],
                           f"bytes 0-{len(invalid) - 1}/{len(invalid)}",
                           len(invalid), BytesIO(invalid))

            with self.assertRaises(portal_uploads.UploadError) as error:
                uploads.finalize("guest", created["id"])

            self.assertEqual(error.exception.status, 422)
            self.assertFalse((uploads.root / f"{created['id']}.partial").exists())
            uploads.close()

    def test_audio_size_limit_is_lower_than_video_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            uploads = self.manager(Path(folder) / "uploads")
            with self.assertRaises(portal_uploads.UploadError) as error:
                uploads.create("guest", "large.wav",
                               portal_uploads.MAX_AUDIO_UPLOAD_BYTES + 1)
            self.assertEqual(error.exception.status, 413)
            uploads.close()

    def test_two_guests_upload_in_parallel_without_cross_session_file_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first_source, second_source = root / "first.mp3", root / "second.mp3"
            self.make_audio(first_source)
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "sine=frequency=880:duration=0.5", "-c:a", "libmp3lame",
                 "-y", str(second_source)],
                check=True, capture_output=True, timeout=20,
            )
            uploads = self.manager(root / "uploads")
            created = [
                uploads.create(owner, source.name, source.stat().st_size)
                for owner, source in (("guest-one", first_source),
                                      ("guest-two", second_source))
            ]
            pairs = (("guest-one", created[0], first_source),
                     ("guest-two", created[1], second_source))
            with ThreadPoolExecutor(max_workers=2) as workers:
                list(workers.map(
                    lambda pair: self.append_file(uploads, pair[0], pair[1]["id"], pair[2]),
                    pairs,
                ))
            with ThreadPoolExecutor(max_workers=2) as workers:
                completed = list(workers.map(
                    lambda pair: uploads.finalize(pair[0], pair[1]["id"]),
                    ((pair[0], pair[1]) for pair in pairs),
                ))

            with self.assertRaises(portal_uploads.UploadError) as denied:
                uploads.status("guest-one", created[1]["id"])
            self.assertEqual(denied.exception.status, 404)
            self.assertNotEqual(completed[0][0], completed[1][0])
            self.assertTrue(all(result[2] for result in completed))
            self.assertFalse(uploads.finalize("guest-one", created[0]["id"])[2])
            uploads.close()
