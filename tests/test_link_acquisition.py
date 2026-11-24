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
            jobs.submit("other-key", MAGNET, "request-2")
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


def test_room_http_submission_requires_auth_csrf_and_consent_and_publishes_progress(tmp_path):
    from test_portal import PortalRig, login, decode

    rig = PortalRig()
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: deliveries.append(args),
                                rig.server.session_key_active)
    rig.server.link_jobs = jobs
    try:
        origin = "http://" + rig.host
        body = {"url": YOUTUBE, "request_id": "browser-1", "authorised": True}
        assert rig.request("POST", "/api/link-jobs", body, origin=origin)[0] == 403
        status, joined, cookie = login(rig, name="Submitter")
        assert status == 200
        csrf = joined["csrf"]
        assert rig.request("POST", "/api/link-jobs", body, cookie=cookie, origin=origin)[0] == 403
        assert rig.request("POST", "/api/link-jobs", {**body, "authorised": False},
                           cookie=cookie, csrf=csrf, origin=origin)[0] == 400
        status, response, _ = rig.request("POST", "/api/link-jobs", body,
                                          cookie=cookie, csrf=csrf, origin=origin)
        assert status == 202
        job_id = decode(response)["id"]
        assert provider.started.wait(2)
        status, response, _ = rig.request("GET", "/api/status", cookie=cookie)
        assert status == 200
        state = decode(response)["state"]
        assert state["link_capabilities"] == {"youtube": True, "magnet": True}
        assert state["link_jobs"][0]["id"] == job_id
        assert state["link_jobs"][0]["received"] == 3
        assert state["link_jobs"][0]["can_cancel"]
        assert "abcdefghijk" not in json.dumps(state["link_jobs"])
        status, viewer, other_cookie = login(rig, name="Viewer")
        assert status == 200
        status, response, _ = rig.request("GET", "/api/status", cookie=other_cookie)
        assert status == 200
        assert decode(response)["state"]["link_jobs"][0]["can_cancel"] is False
        assert rig.request("POST", "/api/link-jobs/cancel", {"id": job_id},
                           cookie=other_cookie, csrf=viewer["csrf"], origin=origin)[0] == 404
        provider.resume.set()
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "ready")
        assert len(deliveries) == 1
    finally:
        provider.resume.set()
        rig.close()


def test_host_disabled_by_default_has_truthful_capability_and_rejects_download(tmp_path):
    from test_portal import PortalRig, login, decode

    rig = PortalRig()
    try:
        _, joined, cookie = login(rig)
        status, response, _ = rig.request("GET", "/api/status", cookie=cookie)
        assert status == 200
        assert decode(response)["state"]["link_capabilities"] == {"youtube": False, "magnet": False}
        assert rig.request("POST", "/api/link-jobs",
                           {"url": MAGNET, "request_id": "browser-2", "authorised": True},
                           cookie=cookie, csrf=joined["csrf"], origin="http://" + rig.host)[0] == 503
    finally:
        rig.close()


def test_torrent_adapter_authenticates_metadata_before_downloading_and_probes(monkeypatch, tmp_path):
    from types import SimpleNamespace

    root, digest, info = _torrent(_info())
    source = acquisition.parse_link("magnet:?xt=urn:btih:" + digest + "&tr=http://127.0.0.1")
    provider = acquisition.CommandProvider(("magnet",))
    provider.launcher = "/trusted/sandbox"
    provider.tools["magnet"] = "/trusted/aria2c"
    provider.probe = "/trusted/ffprobe"
    calls = []
    stages = []

    def fake_run(tool, args, directory, cancelled, progress, deadline):
        calls.append((tool, args))
        if "--bt-metadata-only=true" in args:
            assert args[-1] == source.url
            assert "127.0.0.1" not in " ".join(args)
            (directory / (digest + ".torrent")).write_bytes(root)
        else:
            assert "--select-file=1" in args and "--check-integrity=true" in args
            assert Path(args[-1]).read_bytes() == b"d4:info" + info + b"e"
            assert "--dir=" + str(directory / "payload") in args
            (directory / "payload" / "demo.mp4").write_bytes(b"testdata")
            progress(8, 8)

    def fake_probe(command, **kwargs):
        assert command[:2] == [provider.launcher, provider.probe]
        assert command[command.index("-protocol_whitelist") + 1] == "file,pipe"
        assert kwargs["timeout"] == 30
        return SimpleNamespace(returncode=0, stdout=b"video\n")

    monkeypatch.setattr(provider, "_run", fake_run)
    monkeypatch.setattr(acquisition.subprocess, "run", fake_probe)
    path = provider.acquire(source, tmp_path, stages.append, lambda *args: None, lambda: False)
    assert path == tmp_path / "payload" / "demo.mp4"
    assert len(calls) == 2
    assert stages == ["resolving", "downloading", "verifying"]


def test_youtube_adapter_uses_canonical_video_not_playlist_or_user_options(monkeypatch, tmp_path):
    from types import SimpleNamespace

    provider = acquisition.CommandProvider(("youtube",))
    provider.launcher = "/trusted/sandbox"
    provider.tools["youtube"] = "/trusted/yt-dlp"
    provider.probe = "/trusted/ffprobe"
    calls = []
    stages = []

    def fake_run(tool, args, directory, cancelled, progress, deadline):
        calls.append((tool, args))
        assert args[-1] == YOUTUBE
        assert "--ignore-config" in args and "--no-playlist" in args and "--no-cookies" in args
        assert "--max-filesize" in args
        (directory / "example.mp4").write_bytes(b"testdata")

    monkeypatch.setattr(provider, "_run", fake_run)
    monkeypatch.setattr(acquisition.subprocess, "run", lambda *args, **kw:
                        SimpleNamespace(returncode=0, stdout=b"audio\nvideo\n"))
    source = acquisition.parse_link("https://youtu.be/abcdefghijk?list=other")
    assert provider.acquire(source, tmp_path, stages.append, lambda *args: None, lambda: False).name == "example.mp4"
    assert len(calls) == 1
    assert stages == ["downloading", "verifying"]


def test_readiness_does_not_treat_directory_as_launcher_or_execute_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: None if name == "aria2c" else "/trusted/" + name)
    monkeypatch.setattr(acquisition.subprocess, "run", lambda *args, **kwargs: pytest.fail("UI must not run probes"))
    provider = acquisition.CommandProvider(("youtube", "magnet"), launcher=str(tmp_path))
    assert provider.capabilities() == {"youtube": False, "magnet": False}
    assert provider.readiness()["youtube"]["missing"] == ["owner-configured isolation launcher"]
    assert provider.readiness()["magnet"]["missing"] == ["aria2c", "owner-configured isolation launcher"]
    assert provider.readiness()["youtube"]["isolation_verified"] is False
    assert "isolation launcher" in provider.readiness_text("youtube")


def test_headless_worker_diagnostics_report_missing_and_failed_tools_without_paths(monkeypatch, capsys):
    from types import SimpleNamespace

    monkeypatch.delenv("SMOOTHCAST_LINK_SANDBOX", raising=False)
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: None if name == "aria2c" else "/private/" + name)
    calls = []

    def probe(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 5
        if command[0].endswith("ffprobe"):
            raise acquisition.subprocess.TimeoutExpired(command, 5)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(acquisition.subprocess, "run", probe)
    assert acquisition.diagnostics_main(["--tools-only"]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["tools"] == {"yt-dlp": "executable", "aria2c": "missing", "ffprobe": "probe_timed_out"}
    assert report["launcher_configured"] is False and report["isolation_verified"] is False
    assert "/private/" not in output
    assert len(calls) == 2


def test_tools_only_success_is_not_a_claim_of_isolation(monkeypatch, capsys):
    from types import SimpleNamespace

    monkeypatch.delenv("SMOOTHCAST_LINK_SANDBOX", raising=False)
    monkeypatch.setattr(acquisition.shutil, "which", lambda name: "/trusted/" + name)
    monkeypatch.setattr(acquisition.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    assert acquisition.diagnostics_main(["--tools-only"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["isolation_verified"] is False
    assert acquisition.diagnostics_main([]) == 1


def test_installed_cli_routes_link_check_before_gui(monkeypatch):
    import cli
    import sys

    monkeypatch.setattr(sys, "argv", ["smoothcast", "--link-check", "--tools-only"])
    monkeypatch.setattr(acquisition, "diagnostics_main",
                        lambda args: 17 if args == ["--tools-only"] else 99)
    assert cli.main() == 17
