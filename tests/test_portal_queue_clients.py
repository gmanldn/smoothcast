"""Three guests adding to Up Next: retries and races never duplicate or drop items."""
from __future__ import annotations

from pathlib import Path
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cast_portal_queue import PortalQueueMixin


class Room(PortalQueueMixin):
    def __init__(self, root: Path):
        self.queue: list[str] = []
        self.queue_durations = {}
        self.now_playing = "/private/playing.mkv"
        self.session = object()
        self.busy = True  # receiver preparation in flight
        self.selected_index = None
        self._portal = SimpleNamespace(server=SimpleNamespace(uploads=SimpleNamespace(root=root)))
        self._gtk = threading.Lock()  # the portal marshals every edit onto one GTK thread

    def _enqueue(self, paths):
        self.queue.extend(paths)

    def _rebuild_queue(self):
        pass

    def add(self, path: Path, name: str = "x.mp4"):
        with self._gtk:
            return self._portal_queue_action("queue_add", {"path": str(path), "name": name})


def _files(tmp_path: Path, count: int) -> list[Path]:
    paths = []
    for index in range(count):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        paths.append(path)
    return paths


def test_three_guests_retrying_the_same_upload_queue_it_once(tmp_path):
    room = Room(tmp_path)
    clip, = _files(tmp_path, 1)
    barrier = threading.Barrier(3)

    def guest():
        barrier.wait()
        for _ in range(5):
            assert room.add(clip) == "Added to the queue."

    threads = [threading.Thread(target=guest) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert room.queue == [str(clip)]
    assert room.now_playing == "/private/playing.mkv"


def test_concurrent_distinct_uploads_all_land_exactly_once_while_busy(tmp_path):
    room = Room(tmp_path)
    clips = _files(tmp_path, 9)
    barrier = threading.Barrier(3)

    def guest(mine):
        barrier.wait()
        for clip in mine:
            room.add(clip)
            room.add(clip)  # duplicate retry

    threads = [threading.Thread(target=guest, args=(clips[i::3],)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(room.queue) == sorted(str(clip) for clip in clips)
    assert room.session is not None and room.now_playing == "/private/playing.mkv"


def test_rejoining_guest_sees_committed_queue_without_duplicates(tmp_path):
    room = Room(tmp_path)
    clips = _files(tmp_path, 2)
    for clip in clips:
        room.add(clip)
    before = [row["id"] for row in room._portal_queue_status()]
    room.add(clips[0])  # reconnect replays the last submit
    assert [row["id"] for row in room._portal_queue_status()] == before
