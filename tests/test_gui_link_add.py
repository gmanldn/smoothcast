"""Headless contract for the GUI's Add-from-YouTube core; no GTK, network or receivers."""
from __future__ import annotations

import json
import time

import pytest

import gui_link_add
import link_acquisition as acquisition

YOUTUBE = "https://www.youtube.com/watch?v=abcdefghijk"


class Provider:
    def capabilities(self):
        return {"youtube": True, "magnet": False}

    def acquire(self, source, root, stage, progress, cancelled):
        stage("downloading")
        progress(4, 8)
        stage("verifying")
        path = root / "clip.mp4"
        path.write_bytes(b"testdata")
        return path


def _wait(predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end and not predicate():
        time.sleep(0.01)
    assert predicate()


@pytest.mark.parametrize("text,expected", [
    (YOUTUBE, True), ("https://youtu.be/abcdefghijk?t=3", True),
    ("https://example.com/a.mp4", False), ("magnet:?xt=urn:btih:" + "a" * 40, False),
    ("", False), (None, False), ("https://www.youtube.com/playlist?list=x", False),
])
def test_is_youtube_only_for_single_videos(text, expected):
    assert gui_link_add.is_youtube(text) is expected


def test_gui_owner_acquires_and_enqueues_once_and_guests_keep_their_delivery(tmp_path):
    guest_deliveries, queued = [], []
    jobs = acquisition.LinkJobs(tmp_path, Provider(), lambda o, p: guest_deliveries.append((o, p)),
                                lambda key: key == "guest-key")
    try:
        assert gui_link_add.attach(jobs, queued.append)
        assert gui_link_add.attach(jobs, queued.append)         # idempotent, no double wrap
        result = gui_link_add.submit(jobs, YOUTUBE)
        assert result.ok and result.job_id
        _wait(lambda: gui_link_add.describe(jobs, result.job_id)[1])
        assert len(queued) == 1 and queued[0].name == "clip.mp4" and not guest_deliveries
        assert gui_link_add.describe(jobs, result.job_id) == ("Added to Up Next", True)
        # A web guest is still delivered through the portal authority.
        jobs.submit("guest-key", "https://youtu.be/zzzzzzzzzzz", "guest-req-1")
        _wait(lambda: guest_deliveries)
        assert len(queued) == 1
    finally:
        jobs.close()


def test_progress_text_hides_url_and_unavailable_worker_is_explained(tmp_path):
    jobs = acquisition.LinkJobs(tmp_path, Provider(), lambda *a: None, lambda key: False)
    try:
        gui_link_add.attach(jobs, lambda path: None)
        result = gui_link_add.submit(jobs, YOUTUBE)
        _wait(lambda: gui_link_add.describe(jobs, result.job_id)[1])
        text = gui_link_add.describe(jobs, result.job_id)[0]
        assert "abcdefghijk" not in text and "youtube" not in text.lower()
    finally:
        jobs.close()
    none = gui_link_add.submit(None, YOUTUBE)
    assert not none.ok and "isolated worker" in none.message
    assert not gui_link_add.attach(None, lambda path: None)


def test_invalid_link_returns_friendly_error_without_running_a_worker(tmp_path):
    jobs = acquisition.LinkJobs(tmp_path, Provider(), lambda *a: None, lambda key: False)
    try:
        gui_link_add.attach(jobs, lambda path: None)
        result = gui_link_add.submit(jobs, "https://evil.invalid/watch?v=abcdefghijk")
        assert not result.ok and json.dumps(result.message)
        assert jobs.snapshot() == []
    finally:
        jobs.close()
