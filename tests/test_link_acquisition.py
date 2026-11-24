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


def _journal_payload(*rows):
    return {"schema": acquisition.JOURNAL_SCHEMA, "jobs": [
        {"id": ident, "kind": "youtube", "identity": "abcdefghijk", "stage": stage}
        for ident, stage in rows
    ]}


def test_restart_recovers_uncertain_delivery_without_automatic_replay(tmp_path):
    journal = tmp_path / "acquisition-journal.json"
    ident = "a" * 24
    journal.write_text(json.dumps(_journal_payload((ident, "queueing"))), encoding="utf-8")
    path = tmp_path / ident / "sample.mp4"
    path.parent.mkdir()
    path.write_bytes(b"previously acquired")
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: deliveries.append(args), lambda owner: True)
    try:
        row = jobs.snapshot("new-session")[0]
        assert row["stage"] == "delivery_uncertain"
        assert row["can_cancel"] is False
        assert jobs.submit("new-session", YOUTUBE, "new-request") == ident
        assert provider.calls == [] and deliveries == []
        assert path.read_bytes() == b"previously acquired"
    finally:
        jobs.close()


def test_interrupted_download_requires_new_authorised_submission(tmp_path):
    ident = "b" * 24
    journal = tmp_path / "acquisition-journal.json"
    journal.write_text(json.dumps(_journal_payload((ident, "resolving"))), encoding="utf-8")
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: deliveries.append(args), lambda owner: True)
    try:
        assert jobs.snapshot()[0]["stage"] == "failed"
        assert not provider.calls
        new_id = jobs.submit("fresh-session", YOUTUBE, "fresh-request")
        assert new_id != ident and provider.started.wait(2)
        provider.resume.set()
        _wait_for(lambda: jobs.snapshot()[-1]["stage"] == "ready")
        assert len(deliveries) == 1
        payload = journal.read_text()
        assert "fresh-session" not in payload and "fresh-request" not in payload
    finally:
        provider.resume.set()
        jobs.close()


def test_queue_delivery_intent_is_on_disk_before_dispatch(tmp_path):
    provider = FakeProvider()
    provider.resume.set()
    receipts = []

    def deliver(owner, path):
        receipt = json.loads((tmp_path / "acquisition-journal.json").read_text())
        receipts.append(receipt["jobs"][-1])
        assert receipt["jobs"][-1]["stage"] == "queueing"
        assert path.read_bytes() == b"testdata"

    jobs = acquisition.LinkJobs(tmp_path, provider, deliver, lambda owner: True)
    try:
        ident = jobs.submit("secret-session", YOUTUBE, "secret-request")
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "ready")
        import hashlib
        assert receipts == [{"id": ident, "kind": "youtube", "identity": "abcdefghijk",
                             "stage": "queueing", "size": 8,
                             "sha256": hashlib.sha256(b"testdata").hexdigest()}]
        saved = (tmp_path / "acquisition-journal.json").read_text()
        assert json.loads(saved)["jobs"][0]["stage"] == "ready"
        assert "secret" not in saved and "sample.mp4" not in saved
    finally:
        jobs.close()


def test_write_failure_before_queue_delivery_never_dispatches(monkeypatch, tmp_path):
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: deliveries.append(args), lambda owner: True)
    try:
        assert jobs._journal is not None
        save = jobs._journal.save

        def fail_queueing(rows):
            rows = list(rows)
            if any(row.stage == "queueing" for row in rows):
                raise OSError("simulated disk full")
            save(rows)

        monkeypatch.setattr(jobs._journal, "save", fail_queueing)
        ident = jobs.submit("owner", YOUTUBE, "request")
        assert provider.started.wait(2)
        provider.resume.set()
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "failed")
        assert not deliveries and not jobs.storage_available()
        _wait_for(lambda: not (tmp_path / ident).exists())
        assert json.loads((tmp_path / "acquisition-journal.json").read_text())["jobs"][0]["stage"] == "resolving"
    finally:
        provider.resume.set()
        jobs.close()


def test_write_failure_after_dispatch_preserves_media_and_uncertain_receipt(monkeypatch, tmp_path):
    provider = FakeProvider()
    provider.resume.set()
    delivered = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: delivered.append(path), lambda owner: True)
    try:
        save = jobs._journal.save

        def fail_ready(rows):
            rows = list(rows)
            if any(row.stage == "ready" for row in rows):
                raise OSError("simulated disk full")
            save(rows)

        monkeypatch.setattr(jobs._journal, "save", fail_ready)
        jobs.submit("owner", YOUTUBE, "request")
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "delivery_uncertain")
        assert len(delivered) == 1 and delivered[0].read_bytes() == b"testdata"
        assert json.loads((tmp_path / "acquisition-journal.json").read_text())["jobs"][0]["stage"] == "queueing"
    finally:
        jobs.close()


def test_room_restart_cannot_take_cache_lock_until_old_delivery_exits(tmp_path):
    provider = FakeProvider()
    provider.resume.set()
    entered = threading.Event()
    release = threading.Event()

    def deliver(owner, path):
        entered.set()
        assert release.wait(3)

    old = acquisition.LinkJobs(tmp_path, provider, deliver, lambda owner: True)
    new = None
    try:
        old.submit("owner", YOUTUBE, "request")
        assert entered.wait(2)
        old.close()
        blocked = acquisition.LinkJobs(tmp_path, FakeProvider(), lambda *args: None, lambda owner: True)
        try:
            assert blocked.capabilities() == {"youtube": False, "magnet": False}
            with pytest.raises(acquisition.LinkError, match="recovery storage"):
                blocked.submit("new-owner", MAGNET, "another-request")
        finally:
            blocked.close()
        release.set()
        _wait_for(lambda: old._worker is None)
        new = acquisition.LinkJobs(tmp_path, FakeProvider(), lambda *args: None, lambda owner: True)
        assert new.storage_available()
        assert new.snapshot()[0]["stage"] == "ready"
    finally:
        release.set()
        old.close()
        if new:
            new.close()


def test_corrupt_journal_is_preserved_and_blocks_new_downloads(tmp_path):
    journal = tmp_path / "acquisition-journal.json"
    journal.write_text('{"schema":999,"jobs":[]}', encoding="utf-8")
    provider = FakeProvider()
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: None, lambda owner: True)
    try:
        assert not jobs.storage_available()
        with pytest.raises(acquisition.LinkError, match="recovery storage"):
            jobs.submit("owner", YOUTUBE, "request")
        assert not provider.calls
        assert journal.read_text() == '{"schema":999,"jobs":[]}'
    finally:
        jobs.close()


def test_retained_cache_budget_preserves_previous_media(monkeypatch, tmp_path):
    existing = tmp_path / ("a" * 24)
    existing.mkdir()
    media = existing / "queued.mp4"
    media.write_bytes(b"existing")
    monkeypatch.setattr(acquisition, "MAX_CACHE_BYTES", acquisition.MAX_BYTES)
    provider = FakeProvider()
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: None, lambda owner: True)
    try:
        jobs.submit("owner", YOUTUBE, "request")
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "failed")
        assert "cache is full" in jobs.snapshot()[0]["error"]
        assert provider.calls == []
        assert media.read_bytes() == b"existing"
    finally:
        jobs.close()


def test_youtube_search_results_are_projected_and_bounded():
    row = {"id": "abcdefghijk", "title": "Example", "channel": "Artist",
           "duration": 91.9, "url": "http://127.0.0.1/private", "thumbnail": "secret"}
    raw = [
        row, row, {**row, "id": "invalid"}, {**row, "id": "abcdefghij1", "is_live": True},
        {**row, "id": "abcdefghij2", "ie_key": "Other"},
        {**row, "id": "abcdefghij3", "_type": "playlist"},
        *[{**row, "id": f"video{i:06d}"} for i in range(15)],
    ]
    results = acquisition.youtube_results(b"\n".join(json.dumps(v).encode() for v in raw))
    assert len(results) == 10
    assert results[0] == {"id": "abcdefghijk", "title": "Example", "channel": "Artist", "duration": 91}
    assert len({r["id"] for r in results}) == 10
    assert "127.0.0.1" not in json.dumps(results) and "secret" not in json.dumps(results)


@pytest.mark.parametrize("query", [None, "", " ", "x" * 201, "bad\nquery", "bad\x00query"])
def test_youtube_search_validates_query_before_worker(monkeypatch, query):
    provider = acquisition.CommandProvider(("youtube",))
    monkeypatch.setattr(acquisition, "_youtube_search_command",
                        lambda *args: pytest.fail("invalid query reached worker"))
    with pytest.raises(acquisition.LinkError) as exc:
        provider.search_youtube(query, lambda: False)
    assert exc.value.status == 400


def test_youtube_search_uses_isolated_metadata_only_command(monkeypatch):
    from types import SimpleNamespace

    provider = acquisition.CommandProvider(("youtube",))
    provider.launcher = "/trusted/sandbox"
    provider.tools["youtube"] = "/trusted/yt-dlp"
    provider.probe = "/trusted/ffprobe"

    def launch(command, **kwargs):
        assert command[:2] == [provider.launcher, provider.tools["youtube"]]
        assert command[-2:] == ["--", "ytsearch10:--exec malicious"]
        assert {"--ignore-config", "--skip-download", "--flat-playlist", "--no-cookies"} <= set(command)
        kwargs["stdout"].write(b'{"id":"abcdefghijk","title":"Example"}\n')
        kwargs["stdout"].flush()
        return SimpleNamespace(poll=lambda: 0, returncode=0)

    monkeypatch.setattr(acquisition.subprocess, "Popen", launch)
    assert provider.search_youtube("--exec malicious", lambda: False)[0]["id"] == "abcdefghijk"


def test_youtube_search_output_and_global_capacity_are_bounded():
    with pytest.raises(acquisition.LinkError, match="too much"):
        acquisition.youtube_results(b"x" * (acquisition.SEARCH_OUTPUT_LIMIT + 1))
    assert acquisition._SEARCH_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(acquisition.LinkError) as exc:
            acquisition._youtube_search_command("/not/run", "/not/run", "query", lambda: False)
        assert exc.value.status == 429
    finally:
        acquisition._SEARCH_SLOT.release()


def test_youtube_search_http_to_verified_queue(tmp_path):
    from test_portal import PortalRig, login, decode

    class SearchProvider(FakeProvider):
        def search_youtube(self, query, cancelled):
            assert query == "example music" and not cancelled()
            return [{"id": "abcdefghijk", "title": "Example", "channel": "Artist", "duration": 90}]

    rig = PortalRig()
    provider = SearchProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: deliveries.append(args),
                                rig.server.session_key_active)
    rig.server.link_jobs = jobs
    try:
        origin = "http://" + rig.host
        route = "/api/search/youtube"
        body = {"q": "example music"}
        assert rig.request("POST", route, body, origin=origin)[0] == 403
        _, joined, cookie = login(rig)
        csrf = joined["csrf"]
        assert rig.request("POST", route, body, cookie=cookie, origin=origin)[0] == 403
        status, response, _ = rig.request("POST", route, body, cookie=cookie, csrf=csrf, origin=origin)
        assert status == 200
        result = decode(response)["results"][0]
        assert result["title"] == "Example" and not provider.calls and not deliveries
        receipt = {"url": "https://www.youtube.com/watch?v=" + result["id"],
                   "request_id": "search-result-1", "authorised": True}
        assert rig.request("POST", "/api/link-jobs", receipt, cookie=cookie,
                           csrf=csrf, origin=origin)[0] == 202
        assert provider.started.wait(2) and not deliveries
        provider.resume.set()
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "ready")
        assert len(deliveries) == 1 and provider.calls == [acquisition.parse_link(YOUTUBE)]
    finally:
        provider.resume.set()
        rig.close()


def test_youtube_search_disabled_and_revoked_session(tmp_path):
    from test_portal import PortalRig, login

    rig = PortalRig()
    try:
        _, joined, cookie = login(rig)
        assert rig.request("POST", "/api/search/youtube", {"q": "example"}, cookie=cookie,
                           csrf=joined["csrf"], origin="http://" + rig.host)[0] == 503
    finally:
        rig.close()

    class RevokedProvider(FakeProvider):
        def search_youtube(self, query, cancelled):
            pytest.fail("revoked guest reached search worker")

    jobs = acquisition.LinkJobs(tmp_path, RevokedProvider(), lambda *args: None, lambda owner: False)
    try:
        with pytest.raises(acquisition.LinkError) as exc:
            jobs.search_youtube("revoked", "example")
        assert exc.value.status == 403
    finally:
        jobs.close()


def test_youtube_find_browser_selects_and_retries_same_queue_request():
    import shutil
    import subprocess

    import portal

    if not shutil.which("node"):
        pytest.skip("Node.js required for YouTube Find browser regression")
    markup = portal._HTML
    start = markup.index('(()=>{\n  const input=$("findInput"),search=$("youtubeSearch")')
    script = markup[start:markup.index("</script>", start)]
    harness = r"""
const assert=require("node:assert/strict");
class Element{
  constructor(){this.children=[];this.events={};this.checked=false;this.hidden=true;this.value="";}
  addEventListener(name,cb){this.events[name]=cb}
  setAttribute(){}
  append(...items){this.children.push(...items)}
  replaceChildren(...items){this.children=items}
  focus(){}
}
const el=Object.fromEntries(["findInput","youtubeSearch","youtubeResultsPanel",
 "youtubeSearchStatus","youtubeResults","youtubeAuthorised"].map(k=>[k,new Element()]));
const $=id=>el[id],document={createElement:()=>new Element()};
let youtubeSearchBusy=false,linkCapabilities={youtube:true},calls=[],fail=true,refreshes=0;
function updateLinkControls(){}
function clock(s){return String(s)}
async function refresh(){refreshes++}
async function post(path,body){
  calls.push({path,body});
  if(path==="/api/search/youtube")return {results:[{id:"abcdefghijk",title:"Example",channel:"Artist",duration:90}]};
  if(fail){fail=false;throw Error("network lost")}
  return {message:"Download accepted"};
}
"""
    scenario = r"""
(async()=>{
  el.findInput.value="example";
  el.findInput.events.input();
  assert.equal(calls.length,0,"local typing never sends a YouTube query");
  await el.youtubeSearch.events.click();
  assert.deepEqual(calls,[{path:"/api/search/youtube",body:{q:"example"}}]);
  assert.equal(el.youtubeResultsPanel.hidden,false);
  const button=el.youtubeResults.children[0].children[1].children[0];
  await button.events.click();
  assert.equal(calls.length,1,"requires explicit authorisation");
  el.youtubeAuthorised.checked=true;
  await button.events.click();
  assert.equal(button.disabled,false);
  await button.events.click();
  assert.equal(calls.length,3);
  assert.deepEqual(calls[1],calls[2],"lost response must preserve request identity");
  assert.equal(calls[2].path,"/api/link-jobs");
  assert.equal(calls[2].body.url,"https://www.youtube.com/watch?v=abcdefghijk");
  assert.equal(calls[2].body.authorised,true);
  assert.equal(button.textContent,"Download requested");
  assert.equal(refreshes,1);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=harness + script + scenario,
                   check=True, text=True, timeout=10)


def _ready_job(tmp_path, deliveries, provider=None):
    provider = provider or FakeProvider()
    provider.resume.set()
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    first = jobs.submit("owner", YOUTUBE, "request-1")
    _wait_for(lambda: jobs.snapshot()[0]["stage"] == "ready")
    return jobs, provider, first


def test_new_request_for_acquired_media_requeues_without_downloading_again(tmp_path):
    deliveries = []
    jobs, provider, first = _ready_job(tmp_path, deliveries)
    try:
        second = jobs.submit("owner", YOUTUBE, "request-2")
        assert second != first
        _wait_for(lambda: any(r["id"] == second and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 1 and len(deliveries) == 2
        assert deliveries[0] == deliveries[1] and deliveries[1].read_bytes() == b"testdata"
        # Replaying either request id is idempotent: no third delivery.
        assert jobs.submit("owner", YOUTUBE, "request-2") == second
        assert len(deliveries) == 2
        saved = (tmp_path / "acquisition-journal.json").read_text()
        assert "sample.mp4" not in saved and str(tmp_path) not in saved
    finally:
        jobs.close()


def test_tampered_retained_media_is_never_requeued_and_is_downloaded_afresh(tmp_path):
    deliveries = []
    jobs, provider, first = _ready_job(tmp_path, deliveries)
    try:
        (tmp_path / first / "sample.mp4").write_bytes(b"evildata")  # same size, other bytes
        second = jobs.submit("owner", YOUTUBE, "request-2")
        _wait_for(lambda: any(r["id"] == second and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 2  # verification failed: acquired again
        assert deliveries[-1].parent.name == second
        assert deliveries[-1].read_bytes() == b"testdata"
    finally:
        jobs.close()


def test_retained_media_survives_a_room_restart_and_is_reused_by_content(tmp_path):
    deliveries = []
    jobs, provider, first = _ready_job(tmp_path, deliveries)
    jobs.close()
    provider2 = FakeProvider()
    provider2.resume.set()
    restarted = acquisition.LinkJobs(tmp_path, provider2,
                                     lambda owner, path: deliveries.append(path), lambda owner: True)
    try:
        second = restarted.submit("owner", YOUTUBE, "request-9")
        _wait_for(lambda: any(r["id"] == second and r["stage"] == "ready" for r in restarted.snapshot()))
        assert provider2.calls == [] and len(deliveries) == 2
    finally:
        restarted.close()


def test_in_flight_source_still_coalesces_instead_of_reusing(tmp_path):
    provider = FakeProvider()
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: None, lambda owner: True)
    try:
        first = jobs.submit("owner", YOUTUBE, "request-1")
        assert provider.started.wait(2)
        assert jobs.submit("owner", YOUTUBE, "request-2") == first
    finally:
        provider.resume.set()
        jobs.close()


class FlakyProvider(FakeProvider):
    """First acquire fails like an unavailable worker, then succeeds."""

    def __init__(self):
        super().__init__()
        self.failures = 0

    def acquire(self, source, root, stage, progress, cancelled):
        self.failures += 1
        if self.failures == 1:
            self.calls.append(source)
            raise acquisition.LinkError(503, "No acquisition worker is available for this link right now.")
        return super().acquire(source, root, stage, progress, cancelled)


def _failed_job(tmp_path, provider, deliveries):
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    ident = jobs.submit("owner", YOUTUBE, "request-1")
    _wait_for(lambda: any(r["id"] == ident and r["stage"] == "failed" for r in jobs.snapshot()))
    return jobs, ident


def test_retry_of_a_failed_row_downloads_and_delivers_exactly_once(tmp_path):
    provider = FlakyProvider()
    deliveries = []
    jobs, failed = _failed_job(tmp_path, provider, deliveries)
    try:
        rows = {r["id"]: r for r in jobs.snapshot("owner")}
        assert rows[failed]["can_retry"] is True and rows[failed]["can_cancel"] is False
        assert "worker" in rows[failed]["error"].lower()
        assert jobs.snapshot("other")[0]["can_retry"] is False
        attempt = jobs.retry("owner", failed)
        assert attempt != failed
        _wait_for(lambda: any(r["id"] == attempt and r["stage"] == "downloading" for r in jobs.snapshot()))
        # A second explicit retry while the attempt runs joins it: never two downloads.
        assert jobs.retry("owner", failed) == attempt
        assert len(provider.calls) == 2
        provider.resume.set()
        _wait_for(lambda: any(r["id"] == attempt and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(deliveries) == 1 and deliveries[0].read_bytes() == b"testdata"
        # Replaying the original submission identifier now follows the retry.
        assert jobs.submit("owner", YOUTUBE, "request-1") == attempt
        with pytest.raises(acquisition.LinkError) as exc:
            jobs.retry("owner", attempt)
        assert exc.value.status == 409
    finally:
        provider.resume.set()
        jobs.close()


def test_retry_is_owner_bound_and_allows_a_cancelled_row(tmp_path):
    provider = FakeProvider()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    try:
        ident = jobs.submit("owner", YOUTUBE, "request-1")
        assert provider.started.wait(2)
        jobs.cancel("owner", ident)
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "cancelled")
        with pytest.raises(acquisition.LinkError) as exc:
            jobs.retry("other", ident)
        assert exc.value.status == 404
        for bad in (None, "z" * 24):
            with pytest.raises(acquisition.LinkError) as exc:
                jobs.retry("owner", bad)
            assert exc.value.status == 404
        assert jobs.snapshot("other")[0]["can_retry"] is False
        attempt = jobs.retry("owner", ident)
        assert attempt != ident
        provider.resume.set()
        _wait_for(lambda: any(r["id"] == attempt and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 2 and len(deliveries) == 1
    finally:
        provider.resume.set()
        jobs.close()


def test_retry_never_pretends_a_disabled_worker_can_try_again(tmp_path, monkeypatch):
    provider = FlakyProvider()
    deliveries = []
    jobs, failed = _failed_job(tmp_path, provider, deliveries)
    try:
        before = jobs.snapshot("owner")
        monkeypatch.setattr(provider, "capabilities", lambda: {"youtube": False, "magnet": False})
        with pytest.raises(acquisition.LinkError) as exc:
            jobs.retry("owner", failed)
        assert exc.value.status == 503
        assert jobs.snapshot("owner") == before and deliveries == []
    finally:
        jobs.close()


def test_retry_reuses_verified_retained_media_without_a_second_download(tmp_path, monkeypatch):
    provider = FakeProvider()
    provider.resume.set()
    deliveries = []
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda owner, path: deliveries.append(path),
                                lambda owner: True)
    holding = {"fail": False}
    real_save = jobs._save

    def gated_save():
        if holding["fail"] and any(j.stage == "queueing" for j in jobs._jobs.values()):
            return False  # freeze the receipt write, like a full disk at queue time
        return real_save()

    monkeypatch.setattr(jobs, "_save", gated_save)
    try:
        jobs.submit("owner", YOUTUBE, "request-1")
        _wait_for(lambda: jobs.snapshot()[0]["stage"] == "ready")
        holding["fail"] = True
        second = jobs.submit("owner", YOUTUBE, "request-2")
        _wait_for(lambda: any(r["id"] == second and r["stage"] == "failed" for r in jobs.snapshot()))
        assert len(provider.calls) == 1 and len(deliveries) == 1
        holding["fail"] = False
        retry = jobs.retry("owner", second)
        _wait_for(lambda: any(r["id"] == retry and r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 1  # verified retained media: no second download
        assert len(deliveries) == 2 and deliveries[1].read_bytes() == b"testdata"
        assert deliveries[0] == deliveries[1]
        saved = (tmp_path / "acquisition-journal.json").read_text()
        assert "sample.mp4" not in saved and str(tmp_path) not in saved
    finally:
        jobs.close()


def test_restart_interrupted_rows_are_not_retryable_by_any_guest(tmp_path):
    ident = "c" * 24
    (tmp_path / "acquisition-journal.json").write_text(
        json.dumps(_journal_payload((ident, "downloading"))), encoding="utf-8")
    jobs = acquisition.LinkJobs(tmp_path, FakeProvider(), lambda *args: None, lambda owner: True)
    try:
        row = jobs.snapshot("some-session")[0]
        assert row["stage"] == "failed" and row["can_retry"] is False
        with pytest.raises(acquisition.LinkError) as exc:
            jobs.retry("some-session", ident)
        assert exc.value.status == 404
    finally:
        jobs.close()


def test_room_http_retry_is_csrf_protected_owner_bound_and_truthful(tmp_path):
    from test_portal import PortalRig, login, decode

    rig = PortalRig()
    provider = FlakyProvider()
    jobs = acquisition.LinkJobs(tmp_path, provider, lambda *args: None, rig.server.session_key_active)
    rig.server.link_jobs = jobs
    try:
        origin = "http://" + rig.host
        _, joined, cookie = login(rig, name="Submitter")
        csrf = joined["csrf"]
        status, response, _ = rig.request(
            "POST", "/api/link-jobs",
            {"url": YOUTUBE, "request_id": "browser-1", "authorised": True},
            cookie=cookie, csrf=csrf, origin=origin)
        assert status == 202
        failed = decode(response)["id"]
        _wait_for(lambda: any(r["id"] == failed and r["stage"] == "failed" for r in jobs.snapshot()))
        status, state, _ = rig.request("GET", "/api/status", cookie=cookie)
        row = next(r for r in decode(state)["state"]["link_jobs"] if r["id"] == failed)
        assert row["can_retry"] is True and "worker" in row["error"].lower()
        # The retry route keeps the same origin/CSRF/session fences as cancel.
        assert rig.request("POST", "/api/link-jobs/retry", {"id": failed},
                           cookie=cookie, origin=origin)[0] == 403
        assert rig.request("POST", "/api/link-jobs/retry", {"id": failed},
                           csrf=csrf, origin=origin)[0] == 403
        _, viewer, other_cookie = login(rig, name="Viewer")
        assert rig.request("POST", "/api/link-jobs/retry", {"id": failed},
                           cookie=other_cookie, csrf=viewer["csrf"], origin=origin)[0] == 404
        status, response, _ = rig.request("POST", "/api/link-jobs/retry", {"id": failed},
                                          cookie=cookie, csrf=csrf, origin=origin)
        assert status == 202 and decode(response)["id"] != failed
        provider.resume.set()
        _wait_for(lambda: any(r["stage"] == "ready" for r in jobs.snapshot()))
        assert len(provider.calls) == 2
    finally:
        provider.resume.set()
        rig.close()
