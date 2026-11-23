"""DLNA discovery, AVTransport, protected HTTP ranges and media preparation."""
from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import dlna
import streamer


DESCRIPTION = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Living &amp; Room TV</friendlyName>
    <modelName>Test DMR</modelName>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <controlURL>/upnp/control/av</controlURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <controlURL>/upnp/control/render</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""
LOCATION = "http://192.168.12.25:1400/desc.xml"


class DlnaCapabilityTests(unittest.TestCase):
    def test_rendering_control_is_optional_and_requires_a_complete_endpoint(self):
        from dataclasses import replace

        renderer = dlna.parse_renderer(DESCRIPTION, LOCATION, "192.168.12.25")
        self.assertTrue(renderer.supports_rendering_control)
        self.assertFalse(replace(renderer, rendering_url="").supports_rendering_control)
        self.assertFalse(replace(renderer, rendering_service="").supports_rendering_control)

    def test_sink_formats_exclude_source_and_other_transports(self):
        from dataclasses import replace
        from xml.etree import ElementTree

        renderer = replace(
            dlna.parse_renderer(DESCRIPTION, LOCATION, "192.168.12.25"),
            connection_url="http://192.168.12.25:1400/connection",
        )
        response = ElementTree.fromstring(
            "<GetProtocolInfoResponse>"
            "<Source>http-get:*:audio/aac:*</Source>"
            "<Sink>http-get:*:Video/MP4:*,rtsp-rtp-udp:*:video/mpeg:*,"
            "malformed,http-get:*:video/webm:DLNA.ORG_OP=01</Sink>"
            "</GetProtocolInfoResponse>"
        )
        with mock.patch.object(dlna, "_soap", return_value=response) as soap:
            self.assertEqual(dlna.advertised_http_formats(renderer),
                             {"video/mp4", "video/webm"})
        soap.assert_called_once_with(renderer, "GetProtocolInfo", {}, connection=True)

        with mock.patch.object(dlna, "_soap", side_effect=dlna.DlnaError("timeout")):
            self.assertEqual(dlna.advertised_http_formats(renderer), set())

    def test_sink_negotiation_prefers_mp4_then_supported_mpeg_ts(self):
        renderer = dlna.parse_renderer(DESCRIPTION, LOCATION, "192.168.12.25")
        for formats in (set(), {"video/mp4"}, {"video/*"}, {"*"}):
            with self.subTest(formats=formats), mock.patch.object(
                dlna, "advertised_http_formats", return_value=formats
            ):
                self.assertEqual(dlna.negotiate_media_type(renderer), "video/mp4")
        for mime in ("video/mpeg", "video/mp2t", "video/vnd.dlna.mpeg-tts"):
            with self.subTest(mime=mime), mock.patch.object(
                dlna, "advertised_http_formats", return_value={mime}
            ):
                self.assertEqual(dlna.negotiate_media_type(renderer), mime)
        with mock.patch.object(dlna, "advertised_http_formats", return_value={"video/webm"}):
            with self.assertRaisesRegex(dlna.DlnaError, "no supported MP4 or MPEG-TS"):
                dlna.negotiate_media_type(renderer)

    def test_absent_service_does_not_make_a_request(self):
        renderer = dlna.parse_renderer(DESCRIPTION, LOCATION, "192.168.12.25")
        with mock.patch.object(dlna, "_soap") as soap:
            self.assertEqual(dlna.advertised_http_formats(renderer), set())
        soap.assert_not_called()


class DlnaDiscoveryTests(unittest.TestCase):
    def test_parser_extracts_renderer_and_services(self):
        renderer = dlna.parse_renderer(DESCRIPTION, LOCATION, "192.168.12.25")
        self.assertEqual(renderer.name, "Living & Room TV")
        self.assertEqual(renderer.host, "192.168.12.25")
        self.assertIn("/upnp/control/av", renderer.transport_url)
        self.assertIn("AVTransport:1", renderer.transport_service)
        self.assertIn("DLNA · Living & Room TV", renderer.key)
        self.assertIn("RenderingControl", renderer.rendering_service)

    def test_parser_extracts_optional_connection_manager(self):
        service = b"""
      <service>
        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
        <controlURL>/upnp/control/connection</controlURL>
      </service>
"""
        description = DESCRIPTION.replace(b"</serviceList>", service + b"</serviceList>")
        renderer = dlna.parse_renderer(description, LOCATION, "192.168.12.25")
        self.assertEqual(renderer.connection_url,
                         "http://192.168.12.25:1400/upnp/control/connection")
        self.assertEqual(renderer.connection_service,
                         "urn:schemas-upnp-org:service:ConnectionManager:1")
        self.assertEqual(dlna.parse_renderer(
            DESCRIPTION, LOCATION, "192.168.12.25").connection_url, "")

    def test_description_must_be_media_renderer(self):
        xml = DESCRIPTION.replace(b"MediaRenderer:1", b"MediaServer:1")
        with self.assertRaisesRegex(dlna.DlnaError, "not a UPnP MediaRenderer"):
            dlna.parse_renderer(xml, LOCATION, "192.168.12.25")

    def test_no_cross_host_service_redirection(self):
        malicious = DESCRIPTION.replace(
            b"/upnp/control/av",
            b"http://192.168.12.99/internal-control",
        )
        with self.assertRaisesRegex(dlna.DlnaError, "private LAN HTTP"):
            dlna.parse_renderer(malicious, LOCATION, "192.168.12.25")

    def test_urlbase_same_host_different_port_and_relative_controls(self):
        location = "http://192.168.12.25:1400/devices/desc.xml"
        base = b"http://192.168.12.25:1520/upnp/root/"
        xml = DESCRIPTION.replace(b"<device>", b"<URLBase>" + base + b"</URLBase><device>", 1)
        xml = xml.replace(b"/upnp/control/av", b"control/av")
        xml = xml.replace(b"/upnp/control/render", b"control/render")
        renderer = dlna.parse_renderer(xml, location, "192.168.12.25")
        self.assertEqual(renderer.transport_url,
                         "http://192.168.12.25:1520/upnp/root/control/av")
        self.assertEqual(renderer.rendering_url,
                         "http://192.168.12.25:1520/upnp/root/control/render")

    def test_missing_urlbase_uses_description_location(self):
        xml = DESCRIPTION.replace(b"/upnp/control/av", b"control/av")
        renderer = dlna.parse_renderer(
            xml, "http://192.168.12.25:1400/devices/desc.xml", "192.168.12.25")
        self.assertEqual(renderer.transport_url,
                         "http://192.168.12.25:1400/devices/control/av")

    def test_urlbase_rejects_off_host_public_and_userinfo(self):
        for base in (b"http://192.168.12.99:1520/", b"http://8.8.8.8/",
                     b"http://attacker@192.168.12.25/", b"https://192.168.12.25/"):
            with self.subTest(base=base):
                xml = DESCRIPTION.replace(b"<device>", b"<URLBase>" + base + b"</URLBase><device>", 1)
                with self.assertRaises(dlna.DlnaError):
                    dlna.parse_renderer(xml, LOCATION, "192.168.12.25")

    def test_no_public_ip_loopback_userinfo_or_hostname_url(self):
        for location, sender in [
            ("http://8.8.8.8/desc", "8.8.8.8"),
            ("http://127.0.0.1/desc", "127.0.0.1"),
            ("http://localhost/desc", "192.168.12.25"),
            ("http://foo@192.168.12.25/desc", "192.168.12.25"),
            ("https://192.168.12.25/desc", "192.168.12.25"),
            # Malformed URLs from a broken device must be rejected, not crash.
            ("http://[/desc", "192.168.12.25"),
            ("http://192.168.12.25]/desc", "192.168.12.25"),
        ]:
            with self.subTest(location=location), self.assertRaises(dlna.DlnaError):
                dlna.parse_renderer(DESCRIPTION, location, sender)

    def test_clock_mapping_and_short_invalid_values(self):
        self.assertEqual(dlna._seconds("01:02:05"), 3725)
        self.assertEqual(dlna._seconds("NaN"), 0)
        self.assertEqual(dlna._clock(3725.8), "01:02:05")
        self.assertEqual(dlna._clock(-5), "00:00:00")


class DlnaSOAPTests(unittest.TestCase):
    def setUp(self):
        self.renderer = dlna.parse_renderer(DESCRIPTION, LOCATION, "192.168.12.25")

    @staticmethod
    def _reply(body):
        result = mock.MagicMock()
        result.status = 200
        result.read.return_value = body
        return result

    def test_set_uri_escapes_title_and_sends_correct_action(self):
        envelope = b"<s:Envelope xmlns:s='urn:test'><s:Body /></s:Envelope>"
        connection = mock.MagicMock()
        connection.getresponse.return_value = self._reply(envelope)
        with mock.patch.object(dlna, "HTTPConnection", return_value=connection):
            dlna.set_uri(self.renderer, "http://192.168.12.2:9000/media/token", "A & <B>")
        args = connection.request.call_args
        self.assertEqual(args.args[0], "POST")
        self.assertEqual(args.args[1], "/upnp/control/av")
        self.assertIn(b"SetAVTransportURI", args.kwargs["body"])
        self.assertIn(b"A &amp;amp; &amp;lt;B&amp;gt;", args.kwargs["body"])
        self.assertIn("AVTransport:1#SetAVTransportURI", args.kwargs["headers"]["SOAPACTION"])

    def test_set_uri_advertises_the_selected_mpeg_ts_mime(self):
        conn = mock.MagicMock()
        conn.getresponse.return_value = self._reply(b"<root />")
        with mock.patch.object(dlna, "HTTPConnection", return_value=conn):
            dlna.set_uri(self.renderer, "http://192.168.12.2/media/token", "Film",
                         media_type="video/vnd.dlna.mpeg-tts")
        self.assertIn(b"http-get:*:video/vnd.dlna.mpeg-tts:*",
                      conn.request.call_args.kwargs["body"])

    def test_play_pause_stop_seek_and_rendering_volume(self):
        envelope = b"<root></root>"
        conn = mock.MagicMock()
        conn.getresponse.return_value = self._reply(envelope)
        with mock.patch.object(dlna, "HTTPConnection", return_value=conn):
            dlna.play(self.renderer)
            dlna.pause(self.renderer)
            dlna.seek(self.renderer, 123.5)
            dlna.volume(self.renderer, 56)
            dlna.set_muted(self.renderer, True)
            dlna.stop(self.renderer)
        bodies = [call.kwargs["body"] for call in conn.request.call_args_list]
        self.assertIn(b"<Target>00:02:03</Target>", bodies[2])
        self.assertIn(b"<DesiredVolume>56</DesiredVolume>", bodies[3])
        self.assertIn(b"<DesiredMute>1</DesiredMute>", bodies[4])
        self.assertEqual(conn.request.call_count, 6)

    def test_absolute_seek_retries_one_transport_timeout(self):
        first = mock.MagicMock()
        first.request.side_effect = TimeoutError("response timed out")
        second = mock.MagicMock()
        second.getresponse.return_value = self._reply(b"<root />")
        with mock.patch.object(dlna, "HTTPConnection", side_effect=[first, second]) as connect:
            dlna.seek(self.renderer, 123.0)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(first.request.call_args, second.request.call_args)

    def test_set_uri_is_not_retried_after_transport_timeout(self):
        conn = mock.MagicMock()
        conn.request.side_effect = TimeoutError("response timed out")
        with mock.patch.object(dlna, "HTTPConnection", return_value=conn):
            with self.assertRaisesRegex(dlna.DlnaError, "SetAVTransportURI failed"):
                dlna.set_uri(self.renderer, "http://192.168.12.2/media/token", "Film")
        conn.request.assert_called_once()

    def test_http_500_fault_surfaces_safe_upnp_error_code(self):
        fault = (
            b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            b'<s:Body><s:Fault><detail><UPnPError>'
            b'<errorCode>710</errorCode><errorDescription>No such object</errorDescription>'
            b'</UPnPError></detail></s:Fault></s:Body></s:Envelope>'
        )
        reply = self._reply(fault)
        reply.status = 500
        connection = mock.MagicMock()
        connection.getresponse.return_value = reply
        with mock.patch.object(dlna, "HTTPConnection", return_value=connection):
            with self.assertRaisesRegex(
                dlna.DlnaError, r"DLNA Seek failed \(HTTP 500; UPnP 710: No such object\)"
            ):
                dlna._soap(self.renderer, "Seek", {"InstanceID": "0"})
        connection.close.assert_called_once()

    def test_malformed_and_oversized_faults_are_not_leaked(self):
        for payload in (b"<broken", b"x" * (dlna.MAX_SOAP_RESPONSE + 1)):
            with self.subTest(size=len(payload)):
                reply = self._reply(payload)
                reply.status = 500
                conn = mock.MagicMock()
                conn.getresponse.return_value = reply
                with mock.patch.object(dlna, "HTTPConnection", return_value=conn):
                    with self.assertRaises(dlna.DlnaError) as result:
                        dlna.seek(self.renderer, 25)
                self.assertNotIn("x" * 200, str(result.exception))
                self.assertNotIn("<broken", str(result.exception))

    def test_upnp_fault_with_http_200_is_an_error(self):
        fault = b"<root><UPnPError><errorCode>701</errorCode></UPnPError></root>"
        conn = mock.MagicMock()
        conn.getresponse.return_value = self._reply(fault)
        with mock.patch.object(dlna, "HTTPConnection", return_value=conn):
            with self.assertRaisesRegex(dlna.DlnaError, "UPnP 701"):
                dlna.play(self.renderer)

    def test_polling_normalizes_state_and_position(self):
        transport = b"<r><CurrentTransportState>PAUSED_PLAYBACK</CurrentTransportState></r>"
        position = b"<r><RelTime>00:10:22</RelTime><TrackDuration>01:35:30</TrackDuration></r>"
        volume = b"<r><CurrentVolume>33</CurrentVolume></r>"
        with mock.patch.object(dlna, "_soap", side_effect=[
            dlna.ET.fromstring(transport), dlna.ET.fromstring(position), dlna.ET.fromstring(volume),
        ]):
            info = dlna.info(self.renderer)
        self.assertEqual(info["player_state"], "PAUSED")
        self.assertEqual(info["current_time"], 622)
        self.assertEqual(info["duration"], 5730)
        self.assertAlmostEqual(info["volume_level"], .33)


class DlnaRangeServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "film.mp4"
        self.data = bytes(range(256)) * 4
        self.path.write_bytes(self.data)
        self.server = dlna.ProgressiveFileServer(self.path, receiver_ip="192.168.12.25")
        self.assertEqual(self.server.httpd.server_address[0], "127.0.0.1")

    def tearDown(self):
        self.server.close()
        self.tmp.cleanup()

    def _request(self, method, path, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.port, timeout=2)
        try:
            conn.request(method, path, headers=headers or {})
            result = conn.getresponse()
            return result.status, dict(result.getheaders()), result.read()
        finally:
            conn.close()

    def test_progressive_full_and_range_responses(self):
        path = "/media/" + self.server.token
        status, headers, body = self._request("GET", path)
        self.assertEqual(status, 200)
        self.assertEqual(body, self.data)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        status, headers, body = self._request("GET", path, {"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(headers["Content-Range"], "bytes 10-19/1024")
        self.assertEqual(body, self.data[10:20])
        status, _, body = self._request("GET", path, {"Range": "bytes=-5"})
        self.assertEqual(status, 206)
        self.assertEqual(body, self.data[-5:])
        status, _, body = self._request("HEAD", path)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_mpeg_ts_response_advertises_negotiated_content_type(self):
        server = dlna.ProgressiveFileServer(
            self.path, receiver_ip="192.168.12.25", media_type=dlna.MPEG_TS_MEDIA_TYPE,
        )
        try:
            conn = HTTPConnection("127.0.0.1", server.port, timeout=2)
            try:
                conn.request("HEAD", "/media/" + server.token)
                response = conn.getresponse()
                status = response.status
                headers = dict(response.getheaders())
                self.assertEqual(response.read(), b"")
            finally:
                conn.close()
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], dlna.MPEG_TS_MEDIA_TYPE)
        finally:
            server.close()

    def test_invalid_ranges_and_unguessable_paths_do_not_leak(self):
        path = "/media/" + self.server.token
        for range_value in ("bytes=1200-1300", "bytes=2-1", "bytes=0-2,5-7"):
            status, _, _ = self._request("GET", path, {"Range": range_value})
            self.assertEqual(status, 416)
        for forbidden in ("/", "/media/wrong", "/../film.mp4", "/session.json"):
            status, _, _ = self._request("GET", forbidden)
            self.assertEqual(status, 404)

    def test_host_header_must_match_the_bound_interface(self):
        path = "/media/" + self.server.token
        for host in (f"127.0.0.1:{self.server.port}", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertEqual(self._request("GET", path, {"Host": host})[0], 200)
        for host in ("evil.example", "192.168.12.2", "127.0.0.1:9999",
                     "127.0.0.1.evil.example", "[::1]"):
            with self.subTest(host=host):
                self.assertEqual(self._request("GET", path, {"Host": host})[0], 400)
                self.assertEqual(self._request("HEAD", path, {"Host": host})[0], 400)

    def test_oversized_range_is_416_without_crashing_server(self):
        path = "/media/" + self.server.token
        status, headers, body = self._request(
            "GET", path, {"Range": "bytes=" + "9" * 512},
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers["Content-Range"], f"bytes */{len(self.data)}")
        self.assertEqual(body, b"")
        # A malformed client must not kill the server's accept loop.
        self.assertEqual(self._request("GET", path)[0], 200)

    def test_receiver_routed_binding_is_exact_and_never_wildcard(self):
        # No NIC or TV required: assert the actual socket bind arguments.
        with mock.patch.object(dlna, "_DLNAMediaHTTPServer") as server_class, \
             mock.patch.object(dlna.threading, "Thread"):
            routed = dlna.ProgressiveFileServer(
                self.path, receiver_ip="192.168.12.25",
                bind_ip="192.168.12.2",
            )
            try:
                self.assertEqual(server_class.call_args.args[0], ("192.168.12.2", 0))
                self.assertIn(routed.token, routed.url("192.168.12.2"))
                with self.assertRaisesRegex(dlna.DlnaError, "not bound"):
                    routed.url("192.168.12.99")
            finally:
                routed.close()

    def test_public_multicast_unspecified_or_hostname_bind_is_refused(self):
        for invalid in ("0.0.0.0", "8.8.8.8", "239.0.0.1",
                        "169.254.1.10", "localhost", "::1", "127.0.0.2"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(dlna.DlnaError, "private LAN"):
                    dlna.ProgressiveFileServer(
                        self.path, receiver_ip="192.168.12.25",
                        bind_ip=invalid,
                    )

    def test_server_url_rejects_localhost_for_real_receiver(self):
        with self.assertRaisesRegex(dlna.DlnaError, "not bound"):
            self.server.url("192.168.12.2")
        with self.assertRaises(dlna.DlnaError):
            self.server.url("127.0.0.1")


class DlnaPrepareTests(unittest.TestCase):
    def test_mkv_h264_aac_is_losslessly_remuxed_to_mp4(self):
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname) / "film.mkv"
            source.write_bytes(b"fake video")
            target = Path(dirname) / "prepared" / "out.mp4"
            media = streamer.MediaInfo(
                path=source, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                width=1280, height=720, fps=24, duration=85,
            )
            def make_file(args, **kwargs):
                Path(args[-1]).write_bytes(b"simulated mp4")
                process = mock.MagicMock()
                process.poll.return_value = 0
                process.returncode = 0
                return process
            with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as run:
                self.assertEqual(dlna.prepare_mp4(media, target), target)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("-c:v") + 1], "copy")
            self.assertIn("+faststart", args)

    def test_mpeg_ts_fallback_remuxes_without_mp4_flags(self):
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname) / "film.mkv"
            source.write_bytes(b"fake video")
            target = Path(dirname) / "prepared" / "out.ts"
            media = streamer.MediaInfo(
                path=source, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                width=1280, height=720, fps=24, duration=85,
            )

            def make_file(args, **kwargs):
                Path(args[-1]).write_bytes(b"simulated MPEG-TS")
                process = mock.MagicMock()
                process.poll.return_value = 0
                process.returncode = 0
                return process

            with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as run:
                self.assertEqual(dlna.prepare_mp4(media, target, muxer="mpegts"), target)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("-f") + 1], "mpegts")
            self.assertNotIn("-movflags", args)

    def test_selected_dts_is_encoded_without_needlessly_reencoding_h264(self):
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname) / "dual-track.mkv"
            source.write_bytes(b"mock dual-audio film")
            media = streamer.MediaInfo(
                path=source, vcodec="h264", acodec="aac", pix_fmt="yuv420p",
                width=1280, height=720, fps=24, duration=5,
                audio_streams=[
                    streamer.AudioTrack(index=0, codec="aac", default=True),
                    streamer.AudioTrack(index=1, codec="dts", channels=6, layout="5.1"),
                ],
            )
            target = Path(dirname) / "prepared.mp4"
            def make_file(args, **kwargs):
                Path(args[-1]).write_bytes(b"mock mp4")
                proc = mock.MagicMock()
                proc.poll.return_value = 0
                proc.returncode = 0
                return proc

            with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as ffmpeg:
                dlna.prepare_mp4(media, target, audio_track=1)
            args = ffmpeg.call_args.args[0]
            self.assertIn("0:a:1?", args)
            self.assertEqual(args[args.index("-c:v") + 1], "copy")
            self.assertEqual(args[args.index("-c:a") + 1], "aac")
            self.assertEqual(args[args.index("-ac") + 1], "2")
            with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as ffmpeg:
                dlna.prepare_mp4(media, target, audio_track=0)
            args = ffmpeg.call_args.args[0]
            self.assertIn("0:a:0?", args)
            self.assertEqual(args[args.index("-c:v") + 1], "copy")
            self.assertEqual(args[args.index("-c:a") + 1], "copy")
            with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as ffmpeg:
                dlna.prepare_mp4(media, target, audio_track=1, audio_profile="dialogue",
                                 audio_delay_ms=50)
            args = ffmpeg.call_args.args[0]
            self.assertIn("0:a:1?", args)
            self.assertEqual(args[args.index("-c:v") + 1], "copy")
            filters = args[args.index("-af") + 1]
            self.assertTrue(filters.startswith("pan=stereo|"))
            self.assertIn(",adelay=delays=50:all=1", filters)

    def test_missing_selected_audio_fails_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname) / "film.mkv"
            source.write_bytes(b"mock")
            media = streamer.MediaInfo(
                path=source, vcodec="h264", acodec="aac",
                audio_streams=[streamer.AudioTrack(index=0, codec="aac")],
            )
            with mock.patch.object(dlna.subprocess, "Popen") as start:
                with self.assertRaisesRegex(dlna.DlnaError, "no longer available"):
                    dlna.prepare_mp4(media, Path(dirname) / "out.mp4", audio_track=3)
                start.assert_not_called()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "Actual FFmpeg/FFprobe required for audio-codec integration")
    def test_real_mkv_second_soundtrack_is_supported_aac_in_mp4(self):
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname) / "dual-tone.mkv"
            output = Path(dirname) / "selected.mp4"
            # AAC is the default soundtrack. FLAC is a deliberately
            # incompatible surround alternative, like DTS, and should be transcoded
            # while preserving the H.264 picture without re-encoding.
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=128x72:r=24:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-f", "lavfi", "-i", "sine=frequency=880:duration=2",
                "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a:0", "aac", "-c:a:1", "flac", "-filter:a:1", "pan=5.1|FC=c0",
                "-disposition:a:0", "default",
                "-disposition:a:1", "0", "-shortest", str(source),
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=25)
            media = streamer.ffprobe(source)
            self.assertEqual([t.codec for t in media.audio_streams], ["aac", "flac"])
            self.assertEqual(media.audio_streams[1].channels, 6)
            dlna.prepare_mp4(media, output, audio_track=1, audio_profile="dialogue")
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type,codec_name,channels", "-of", "json", str(output)],
                check=True, capture_output=True, text=True, timeout=10,
            )
            streams = json.loads(probe.stdout)["streams"]
            self.assertEqual(
                [(item["codec_name"], item["channels"])
                 for item in streams if item["codec_type"] == "audio"],
                [("aac", 2)],
            )
            self.assertEqual(
                [item["codec_name"] for item in streams if item["codec_type"] == "video"],
                ["h264"],
            )

    def test_hevc_mkv_converts_to_8bit_h264_and_aac(self):
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname) / "film.mkv"
            source.write_bytes(b"fake video")
            target = Path(dirname) / "prepared" / "out.mp4"
            media = streamer.MediaInfo(
                path=source, vcodec="hevc", acodec="dts", pix_fmt="yuv420p10le",
                width=3840, height=2160, fps=60, duration=120,
            )
            def make_file(args, **kwargs):
                Path(args[-1]).write_bytes(b"simulated mp4")
                process = mock.MagicMock()
                process.poll.return_value = 0
                process.returncode = 0
                return process
            with mock.patch.object(dlna.subprocess, "Popen", side_effect=make_file) as run:
                dlna.prepare_mp4(media, target)
            args = run.call_args.args[0]
            self.assertIn("libx264", args)
            self.assertIn("yuv420p", args)
            self.assertIn("aac", args)
            self.assertIn("scale=w=1920:h=1080:force_original_aspect_ratio=decrease", args[-6:] if False else " ".join(args))
            self.assertIn("30", args)

    def test_cancelled_ffmpeg_is_terminated_and_partial_file_removed(self):
        import threading
        with tempfile.TemporaryDirectory() as dirname:
            base = Path(dirname)
            source = base / "movie.mkv"
            source.write_bytes(b"input")
            output = base / "out.mp4"
            media = streamer.MediaInfo(
                path=source, vcodec="hevc", acodec="dts",
                width=1280, height=720, duration=30,
            )
            cancel = threading.Event()
            process = mock.MagicMock()
            process.poll.return_value = None

            def launch(args, **kwargs):
                output.write_bytes(b"partial MP4")
                cancel.set()
                return process

            with mock.patch.object(dlna.subprocess, "Popen", side_effect=launch):
                with self.assertRaisesRegex(dlna.DlnaError, "cancelled"):
                    dlna.prepare_mp4(media, output, cancel=cancel)
            process.terminate.assert_called_once()
            self.assertFalse(output.exists())


class DlnaSessionStartTests(unittest.TestCase):
    def _renderer(self):
        return dlna.Renderer(
            name="TV",
            host="192.168.12.25",
            location=LOCATION,
            transport_url="http://192.168.12.25/upnp/control/av",
            transport_service="urn:schemas-upnp-org:service:AVTransport:1",
        )

    def test_preparation_failure_does_not_stop_the_renderer(self):
        # A local preparation error must clean up scratch without sending a
        # Stop (or SetAVTransportURI) to a renderer that is still playing its
        # own content.
        media = streamer.MediaInfo(path=Path("movie.mkv"), vcodec="hevc", acodec="eac3")
        session = dlna.Session()
        session._owns_renderer = True  # a reused session must not retain ownership
        with mock.patch.object(dlna, "prepare_mp4",
                               side_effect=OSError("disk full")) as prepare, \
             mock.patch.object(dlna, "set_uri") as set_uri, \
             mock.patch.object(dlna, "stop") as stop:
            with self.assertRaises(OSError):
                session.start(media, renderer=self._renderer(),
                              local_ip="192.168.12.10", offset=0.0, title="Film")
        prepare.assert_called_once()
        set_uri.assert_not_called()
        stop.assert_not_called()
        self.assertFalse(session._owns_renderer)
        self.assertIsNone(session.tmp)
        self.assertIsNone(session.state)


if __name__ == "__main__":
    unittest.main()
