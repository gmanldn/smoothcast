"""Headless link acquisition contract; no real network/downloads or receivers."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import threading
import time

import pytest

import link_acquisition as acquisition


YOUTUBE = "https://www.youtube.com/watch?v=abcdefghijk"
HASH = "a" * 40
MAGNET = "magnet:?xt=urn:btih:" + HASH


@pytest.mark.parametrize("url", [
    YOUTUBE, "https://youtu.be/abcdefghijk?t=20",
    "https://m.youtube.com/watch?v=abcdefghijk&list=ignored",
    "https://www.youtube.com/shorts/abcdefghijk",
])
def test_youtube_links_canonicalise_to_one_video(url):
    assert acquisition.parse_link(url) == acquisition.Source("youtube", "abcdefghijk")
    assert acquisition.parse_link(url).url == YOUTUBE


def test_magnets_ignore_untrusted_trackers_webseeds_and_display_names():
    source = acquisition.parse_link(MAGNET + "&tr=http%3A%2F%2F127.0.0.1%2Fadmin&"
                                     "ws=file%3A%2F%2F%2Fsecret&dn=untrusted")
    assert source.url == MAGNET
    b32 = base64.b32encode(bytes.fromhex(HASH)).decode()
    assert acquisition.parse_link("magnet:?xt=urn:btih:" + b32) == source


@pytest.mark.parametrize("value", [
    None, "", "file:///etc/passwd", "http://www.youtube.com/watch?v=abcdefghijk",
    "https://www.youtube.com.evil.invalid/watch?v=abcdefghijk",
    "https://user@www.youtube.com/watch?v=abcdefghijk",
    "https://www.youtube.com:444/watch?v=abcdefghijk",
    "https://www.youtube.com/playlist?list=abc",
    YOUTUBE + "&v=12345678901", "magnet:?xt=urn:btmh:abc",
    MAGNET + "&xt=urn:btih:" + "b" * 40,
    "magnet:?xt=urn:btih:bad", YOUTUBE + "\n",
    "https://127.0.0.1/media.mp4", "x" * 1600,
])
def test_invalid_source_never_reaches_a_worker(value):
    # Outer whitespace is deliberately allowed, but embedded whitespace is not.
    if value == YOUTUBE + "\n":
        assert acquisition.parse_link(value).url == YOUTUBE
    else:
        with pytest.raises(acquisition.LinkError):
            acquisition.parse_link(value)


def _encode(value):
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(_encode(item) for item in value) + b"e"
    return b"d" + b"".join(_encode(k) + _encode(v) for k, v in sorted(value.items())) + b"e"


def _torrent(info):
    raw = _encode(info)
    root = _encode({b"announce": b"http://127.0.0.1/admin",
                    b"info": info, b"url-list": b"http://localhost/secret"})
    return root, hashlib.sha1(raw).hexdigest(), raw


def _info(files=None):
    if files is None:
        return {b"name": b"demo.mp4", b"length": 8, b"piece length": 16,
                b"pieces": b"x" * 20}
    total = sum(item[b"length"] for item in files)
    return {b"name": b"demo", b"files": files, b"piece length": 16,
            b"pieces": b"x" * (20 * ((total + 15) // 16))}


def test_torrent_metadata_infohash_and_path_selection():
    raw, digest, info = _torrent(_info([
        {b"length": 1, b"path": [b"notes.txt"]},
        {b"length": 8, b"path": [b"clip.mp4"]},
        {b"length": 3, b"path": [b"audio.mp3"]},
    ]))
    result = acquisition.inspect_torrent(raw, digest)
    assert result.index == 2 and result.size == 8
    assert result.relative == Path("demo/clip.mp4")
    assert result.info == info
    assert b"127.0.0.1" not in result.info and b"url-list" not in result.info
    with pytest.raises(acquisition.LinkError):
        acquisition.inspect_torrent(raw, "b" * 40)


@pytest.mark.parametrize("component", [b"..", b".", b"/etc", b"C:\\secret", b"../escape.mp4",
                                       b"CON.mp4", b"invalid\x00.mp4"])
def test_torrent_rejects_unsafe_paths_before_payload_download(component):
    raw, digest, _ = _torrent(_info([{b"length": 8, b"path": [component]}]))
    with pytest.raises(acquisition.LinkError):
        acquisition.inspect_torrent(raw, digest)


def test_torrent_rejects_private_and_oversized_metadata():
    private = _info()
    private[b"private"] = 1
    raw, digest, _ = _torrent(private)
    with pytest.raises(acquisition.LinkError):
        acquisition.inspect_torrent(raw, digest)
    large = _info()
    large[b"length"] = acquisition.MAX_BYTES + 1
    raw, digest, _ = _torrent(large)
    with pytest.raises(acquisition.LinkError) as exc:
        acquisition.inspect_torrent(raw, digest)
    assert exc.value.status == 413


class FakeProvider:
    def __init__(self):
        self.started = threading.Event()
        self.resume = threading.Event()
        self.calls = []

    def capabilities(self):
        return {"youtube": True, "magnet": True}

    def acquire(self, source, root, stage, progress, cancelled):
        self.calls.append(source)
        stage("downloading")
        progress(3, 8)
        self.started.set()
        while not self.resume.wait(0.01):
            if cancelled():
                raise acquisition.LinkError(409, "Acquisition cancelled.")
        stage("verifying")
        path = root / "sample.mp4"
        path.write_bytes(b"testdata")
        return path


def _wait_for(predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "acquisition did not reach expected state"


def test_room_jobs_progress_dedup_privacy_and_verified_queue_delivery(tmp_path):
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append((owner, path)),
                                lambda owner: True)
    try:
        job_id = jobs.submit("owner-key", YOUTUBE, "request-1")
        assert provider.started.wait(2)
        assert jobs.submit("owner-key", YOUTUBE, "request-1") == job_id
        assert jobs.submit("other-key", "https://youtu.be/abcdefghijk", "request-2") == job_id
        with pytest.raises(acquisition.LinkError):
            jobs.submit("owner-key", MAGNET, "request-1")
        row = jobs.snapshot("owner-key")[0]
        assert row["stage"] == "downloading" and row["received"] == 3 and row["total"] == 8
        assert row["can_cancel"] is True
        assert jobs.snapshot("other-key")[0]["can_cancel"] is False
        assert "owner-key" not in json.dumps(row) and "abcdefghijk" not in json.dumps(row)
        assert not deliveries
        provider.resume.set()
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "ready")
        assert len(deliveries) == 1 and deliveries[0][1].read_bytes() == b"testdata"
        assert jobs.submit("owner-key", YOUTUBE, "request-1") == job_id
        assert len(provider.calls) == 1
    finally:
        provider.resume.set()
        jobs.close()


def test_revocation_or_owner_cancel_stops_acquisition_before_queue(tmp_path):
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: deliveries.append(args),
                                lambda owner: True)
    try:
        job_id = jobs.submit("owner", MAGNET, "request")
        assert provider.started.wait(2)
        with pytest.raises(acquisition.LinkError) as exc:
            jobs.cancel("other", job_id)
        assert exc.value.status == 404
        jobs.revoke({"owner"})
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "cancelled")
        assert not deliveries
        _wait_for(lambda: not (tmp_path / job_id).exists())
    finally:
        provider.resume.set()
        jobs.close()


def test_no_isolation_launcher_means_no_external_worker(monkeypatch):
    monkeypatch.delenv("SMOOTHCAST_LINK_SANDBOX", raising=False)
    provider = acquisition.CommandProvider(("youtube", "magnet"))
    assert provider.capabilities() == {"youtube": False, "magnet": False}
