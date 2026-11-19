"""SC-062: real HTTP and encoder isolation for every HLS generation.

All tests are offline: loopback-bound HTTP on an ephemeral port, mocked
FFmpeg and Cast processes, and temporary cache directories. No GUI/TV.
"""
from __future__ import annotations

from contextlib import ExitStack
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import mock

import server
import streamer


def test_generation_names_accept_only_canonical_128_bit_hex_identifiers():
    token = "a" * 32
    assert streamer._hls_names_from_url(
        f"http://192.168.1.2:8767/movie-{token}.m3u8"
    ) == (f"movie-{token}.m3u8", f"segment-{token}-*.ts")
    assert streamer._hls_names_from_url(
        "http://192.168.1.2:8767/movie.m3u8"
    ) == (streamer.HLS_NAME, streamer.SEGMENT_GLOB)
    for invalid in (
        "", "http://x/session.json", "http://x/movie-not-hex.m3u8",
        f"http://x/movie-{token.upper()}.m3u8",
        f"http://x/subdir/movie-{token}.m3u8",
        f"http://x/movie-{token}.m3u8/extra",
    ):
        assert streamer._hls_names_from_url(invalid) == ("", "")


def test_missing_saved_stream_url_cannot_scan_all_cached_media(tmp_path):
    session = streamer.Session()
    assert session._count_segments(tmp_path, "") == 0
    state = streamer.SessionState(
        file="/missing.mkv", mode="transcode", offset=0, duration=9,
        device="TV", title="Old", stream_url="",
    )
    # Exercise real restore/sampler lifecycle but without reading live cache.
    with mock.patch.object(streamer, "ROOT", tmp_path), \
         mock.patch.object(streamer, "_pid_is_ours", return_value=False):
        session.restore(state)
        try:
            assert session.segment_count() == 0
            assert session.recoverable_hls() is False
        finally:
            session._stop_sampler()


def test_allowed_resources_reject_aliases_and_other_private_files():
    token = "b" * 32
    for allowed in (
        "/movie.m3u8", "/segment-00012.ts",
        f"/movie-{token}.m3u8",
        f"/segment-{token}-00012.ts",
    ):
        assert server.public_resource(allowed), allowed
    for denied in (
        "/session.json", "/ffmpeg.log", "/", "/burned_subs.srt",
        "/movie-anything.m3u8", "/segment-anything-00000.ts",
        f"/movie-{token.upper()}.m3u8",
        f"/segment-{token}-other.ts",
        f"/subdir/segment-{token}-00012.ts",
        f"/segment-{token}-00012.ts/../session.json",
        f"/segment-{token}-%30%30%30%31%32.ts",
        f"/movie-{token}.m3u8%2F..",
    ):
        assert not server.public_resource(denied), denied


def test_delayed_http_requests_never_receive_new_timeline_bytes():
    old, new = "c" * 32, "d" * 32
    with TemporaryDirectory() as directory:
        root = Path(directory)
        with mock.patch.object(server, "ROOT", root):
            old_playlist = root / f"movie-{old}.m3u8"
            old_segment = root / f"segment-{old}-00000.ts"
            new_playlist = root / f"movie-{new}.m3u8"
            new_segment = root / f"segment-{new}-00000.ts"
            old_playlist.write_bytes(b"#EXTM3U\nOLD PLAYLIST\n")
            old_segment.write_bytes(b"OLD FRAME")
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                def fetch(path, method="GET"):
                    conn = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=3)
                    try:
                        conn.request(method, path)
                        response = conn.getresponse()
                        return response.status, response.read(), dict(response.getheaders())
                    finally:
                        conn.close()

                assert fetch(f"/movie-{old}.m3u8")[:2] == (200, b"#EXTM3U\nOLD PLAYLIST\n")
                assert fetch(f"/segment-{old}-00000.ts")[:2] == (200, b"OLD FRAME")
                old_playlist.unlink()
                old_segment.unlink()
                new_playlist.write_bytes(b"#EXTM3U\nNEW PLAYLIST\n")
                new_segment.write_bytes(b"NEW FRAME")
                for method in ("GET", "HEAD"):
                    assert fetch(f"/movie-{old}.m3u8", method)[0] == 404
                    assert fetch(f"/segment-{old}-00000.ts", method)[0] == 404
                assert fetch(f"/movie-{new}.m3u8")[:2] == (200, b"#EXTM3U\nNEW PLAYLIST\n")
                assert fetch(f"/segment-{new}-00000.ts")[:2] == (200, b"NEW FRAME")
                assert fetch(f"/segment-{new}-00000.ts", "HEAD")[:2] == (200, b"")
                assert fetch("/session.json")[0] == 404
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)


def test_finalized_recovery_only_accepts_own_generation_segments():
    old, other = "a" * 32, "f" * 32
    with TemporaryDirectory() as directory:
        root = Path(directory)
        media = f"movie-{old}.m3u8"
        segment = f"segment-{old}-00000.ts"
        entry = root / media
        (root / segment).write_bytes(b"TS")
        entry.write_text(
            "#EXTM3U\n#EXTINF:2,\n" + segment + "\n#EXT-X-ENDLIST\n"
        )
        session = streamer.Session()
        session.state = streamer.SessionState(
            file="/film.mkv", mode="transcode", offset=0, duration=2,
            device="TV", title="Film",
            stream_url=f"http://192.168.1.9:8767/{media}",
        )
        session.ffmpeg = mock.Mock()
        session.ffmpeg.poll.return_value = 0
        with mock.patch.object(streamer, "ROOT", root), \
             mock.patch.object(streamer, "_server_healthy", return_value=True):
            assert session.recoverable_hls()
            # Exact generation is mandatory, not merely any complete
            # segment existing in the shared cache.
            entry.write_text(
                "#EXTM3U\n#EXTINF:2,\n"
                f"segment-{other}-00000.ts\n#EXT-X-ENDLIST\n"
            )
            (root / f"segment-{other}-00000.ts").write_bytes(b"FOREIGN")
            assert not session.recoverable_hls()
            session.state.stream_url = "http://192.168.1.9:8767/session.json"
            assert not session.recoverable_hls()


def test_each_encoder_start_generates_unreused_url_and_segment_template():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        proc = mock.Mock(pid=12345)
        proc.poll.return_value = 0
        media = streamer.MediaInfo(path=root / "source.mp4", duration=8, width=640, height=360)
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(streamer, "ROOT", root))
            stack.enter_context(mock.patch.object(streamer, "PROGRESS_FILE", root / "progress.log"))
            stack.enter_context(mock.patch.object(streamer, "FFMPEG_LOG", root / "ffmpeg.log"))
            stack.enter_context(mock.patch.object(streamer, "host_ip", return_value="192.168.1.9"))
            stack.enter_context(mock.patch.object(streamer.time, "sleep"))
            stack.enter_context(mock.patch.object(streamer, "_save_session"))
            popen = stack.enter_context(mock.patch.object(streamer.subprocess, "Popen", return_value=proc))
            urls = []
            for i in range(2):
                session = streamer.Session()
                stack.enter_context(mock.patch.object(session, "_start_server"))
                stack.enter_context(mock.patch.object(session, "_await_receiver"))
                stack.enter_context(mock.patch.object(session, "_start_sampler"))
                stack.enter_context(mock.patch.object(session, "_wait_for_segments", return_value=True))
                session.start_transcode(
                    media, 3.0 + i, device="TV", quality="balanced",
                    audio_profile="original", subs_file=None, burn_subs=False, title="Film",
                    device_ip="192.168.1.40",
                )
                url = session.state.stream_url
                urls.append(url)
                token = url.split("/movie-", 1)[1].split(".m3u8", 1)[0]
                assert len(token) == 32
                assert all(ch in "0123456789abcdef" for ch in token)
                assert session.state.offset == 3.0 + i
                ffmpeg_args = popen.call_args_list[-2].args[0]
                assert str(root / f"movie-{token}.m3u8") in ffmpeg_args
                assert str(root / f"segment-{token}-%05d.ts") in ffmpeg_args
                assert url in popen.call_args_list[-1].args[0]
            assert len(set(urls)) == 2
