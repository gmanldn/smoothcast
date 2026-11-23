"""Bounded HLS fetching against SmoothCast's real loopback HTTP handler."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pychromecast
import pytest

import castctl
import server as hls_server
from fakecast import FakeCastReceiver
from fakecast.media import HlsFetcher, MediaFetchError
from pychromecast_backend import PyChromecastBackend


@pytest.fixture
def media_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(hls_server, "ROOT", tmp_path)
    token = "0123456789abcdef0123456789abcdef"
    segment_name = f"segment-{token}-0.ts"
    (tmp_path / segment_name).write_bytes(b"0123456789abcdefghij")
    (tmp_path / f"movie-{token}.m3u8").write_text(
        "#EXTM3U\n#EXT-X-TARGETDURATION:1\n"
        "#EXTINF:0.5,\n#EXT-X-BYTERANGE:10@0\n" + segment_name + "\n"
        "#EXTINF:0.75,\n#EXT-X-BYTERANGE:5@10\n" + segment_name + "\n"
        "#EXT-X-ENDLIST\n",
        "utf-8",
    )
    hls_server.write_policy(
        tmp_path, hls_server.make_policy("127.0.0.1", token=token),
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), hls_server.H)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_port}/movie-{token}.m3u8"
    try:
        yield url
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=1)


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def test_fetches_playlist_and_byte_range_segments_with_cast_mime_and_no_cors(media_endpoint):
    fetcher = HlsFetcher(segment_delay=0.01)
    started = time.monotonic()
    result = fetcher.fetch(media_endpoint)
    elapsed = time.monotonic() - started

    assert result.ended
    assert result.duration == pytest.approx(1.25)
    assert result.segment_count == 2
    assert result.bytes_received == result.requests[0]["bytes"] + 15
    assert [request["status"] for request in result.requests] == [200, 206, 206]
    assert result.requests[0]["content_type"] == "application/vnd.apple.mpegurl"
    assert [request["content_type"] for request in result.requests[1:]] == [
        "video/mp2t", "video/mp2t",
    ]
    assert result.requests[1]["content_range"] == "bytes 0-9/20"
    assert result.requests[2]["content_range"] == "bytes 10-14/20"
    assert result.cors_origins == (None, None, None)
    assert elapsed >= 0.02


def test_rejects_non_loopback_segment_before_network_access(media_endpoint):
    playlist_url = media_endpoint
    body, _content_type, _cors = HlsFetcher()._get(playlist_url)
    text = body.decode().replace(
        "segment-0123456789abcdef0123456789abcdef-0.ts",
        "http://example.com/segment.ts",
    )
    # Exercise the same private parser without making any request to example.com.
    class PlaylistOnlyFetcher(HlsFetcher):
        def _get(self, url, **kwargs):
            if url == playlist_url:
                return text.encode(), "application/vnd.apple.mpegurl", None
            return super()._get(url, **kwargs)

    with pytest.raises(MediaFetchError, match="loopback"):
        PlaylistOnlyFetcher().fetch(playlist_url)


def test_cast_backend_load_fetches_hls_and_emits_buffering_progress_and_finished(
    media_endpoint,
):
    with FakeCastReceiver() as receiver:
        cast = pychromecast.get_chromecast_from_host(
            (receiver.host, receiver.port, uuid.uuid4(), "test-model", "Loopback Receiver"),
            tries=1,
            retry_wait=0.1,
            timeout=1,
        )
        browser = SimpleNamespace(stop_discovery=lambda: None)

        def discover(*, callback, **_kwargs):
            callback(cast)
            return browser

        backend = PyChromecastBackend(discover=discover)
        updates: list[dict[str, object]] = []
        receiver.slow_segments(0.1)
        try:
            assert backend.scan(timeout=0)[0].name == "Loopback Receiver"
            cast.wait(timeout=2)
            cast.start_app("CC1AD845")
            assert wait_for(lambda: any(
                namespace.endswith(".receiver") and data.get("type") == "LAUNCH"
                for namespace, data in receiver.calls
            ))
            unsubscribe = backend.subscribe("Loopback Receiver", updates.append)
            assert backend.command("Loopback Receiver", "cast", media_endpoint)[0]
            assert wait_for(lambda: bool(receiver.media_fetch_results))
            assert receiver.media_fetch_results[0].ended
            assert receiver.media_fetch_results[0].segment_count == 2
            assert wait_for(lambda: any(
                status.get("player_state") == "IDLE"
                and status.get("idle_reason") == "FINISHED"
                for status in updates
            ))
            assert any(
                status.get("player_state") == "BUFFERING" for status in updates
            )
            assert any(
                status.get("player_state") == "PLAYING" for status in updates
            )
            assert max(float(status.get("current_time", 0)) for status in updates) >= 1.25
            unsubscribe()
        finally:
            backend.close()


@pytest.mark.multicast
@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true"
    or os.environ.get("SMOOTHCAST_TEST_CONTEXT") != "1"
    or os.environ.get("SMOOTHCAST_RUN_CATT_CONTRACT") != "1",
    reason="catt discovery contract runs only in its isolated Linux CI job",
)
def test_catt_backend_contract_uses_only_the_loopback_fake(media_endpoint):
    receiver = FakeCastReceiver(port=8009, profile="chromecast-gen2", advertise=True)
    receiver.slow_segments(1)
    try:
        receiver.start()
    except OSError as exc:
        pytest.skip(f"loopback Cast port 8009 is unavailable: {exc}")

    backend = castctl.CattBackend()
    try:
        if not receiver.advertisement_active:
            pytest.skip(f"loopback mDNS unavailable: {receiver.advertising_error}")
        try:
            devices = backend.scan(timeout=15)
        except subprocess.TimeoutExpired:
            pytest.skip("catt scan timed out because loopback multicast is unavailable")
        fake = [
            device for device in devices
            if device.host == "127.0.0.1" and device.port == receiver.port
        ]
        if not fake:
            pytest.skip("catt could not discover the loopback fake over mDNS")
        target = fake[0].name
        assert backend.info(target, timeout=8) is not None
        assert backend.command(target, "cast", media_endpoint, timeout=15)[0]
        assert wait_for(
            lambda: any(data.get("type") == "LOAD" for _ns, data in receiver.calls),
            timeout=5,
        )
        assert backend.command(target, "pause", timeout=8)[0]
        assert wait_for(lambda: bool(receiver.media_fetch_results), timeout=10)
        assert backend.command(target, "stop", timeout=8)[0]
        sent = [data.get("type") for _namespace, data in receiver.calls]
        assert "LOAD" in sent
        assert "PAUSE" in sent
        assert "STOP" in sent
    finally:
        backend.close()
        receiver.stop()

