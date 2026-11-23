"""Deterministic DLNA discovery deadlines and stale GUI rescan protection.

No real SSDP traffic, GTK window, receiver, or user desktop is touched.
"""
from __future__ import annotations

import socket
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dlna
from gui_source import main_window_methods


DESCRIPTION = b"""<?xml version="1.0"?>
<root><device><deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
<friendlyName>Fast TV</friendlyName><serviceList><service>
<serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<controlURL>/upnp/control</controlURL>
</service></serviceList></device></root>"""


class FakeSsdpSocket:
    def __init__(self, replies):
        self.replies = list(replies)
        self.timeout = 0.0
        self.sent = b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def setsockopt(self, *_):
        pass

    def bind(self, *_):
        pass

    def sendto(self, query, _address):
        self.sent = query

    def settimeout(self, timeout):
        self.timeout = timeout

    def recvfrom(self, _limit):
        if self.replies:
            return self.replies.pop(0)
        # Simulate a socket waiting for the remainder of its timeout.
        time.sleep(min(0.01, self.timeout))
        raise socket.timeout()


def reply(ip):
    url = f"http://{ip}:1400/desc.xml"
    return (f"HTTP/1.1 200 OK\r\nLOCATION: {url}\r\n\r\n".encode(), (ip, 1900))


class DeadlineTests(unittest.TestCase):
    def test_fast_tv_survives_several_slow_descriptions_and_global_budget(self):
        fake = FakeSsdpSocket([reply("192.168.12.10"), reply("192.168.12.11"),
                               reply("192.168.12.12"), reply("192.168.12.13")])
        invoked = []
        def fetch(url, *, expected_host, timeout=4.0):
            invoked.append((expected_host, timeout))
            if expected_host == "192.168.12.13":
                return DESCRIPTION
            time.sleep(0.8)
            return DESCRIPTION
        started = time.monotonic()
        with mock.patch.object(dlna.socket, "socket", return_value=fake), \
             mock.patch.object(dlna, "_http_get", side_effect=fetch):
            found = dlna.discover(timeout=0.5)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.73, "slow UPnP descriptions exceeded the scan budget")
        self.assertEqual([device.host for device in found], ["192.168.12.13"])
        self.assertIn(b"\r\nHOST:", fake.sent)
        self.assertTrue(all(0 < t <= 0.5 for _, t in invoked))

    def test_invalid_off_lan_descriptions_are_skipped_before_fetch(self):
        fake = FakeSsdpSocket([reply("8.8.8.8"), reply("192.168.12.42")])
        with mock.patch.object(dlna.socket, "socket", return_value=fake), \
             mock.patch.object(dlna, "_http_get", return_value=DESCRIPTION) as fetch:
            devices = dlna.discover(timeout=0.2)
        self.assertEqual([d.host for d in devices], ["192.168.12.42"])
        self.assertEqual(fetch.call_count, 1)

    def test_timeout_has_lower_and_upper_bounds(self):
        with mock.patch.object(dlna.socket, "socket", return_value=FakeSsdpSocket([])):
            start = time.monotonic()
            self.assertEqual(dlna.discover(timeout=0), [])
            self.assertLess(time.monotonic() - start, 0.7)


class RescanOwnershipTests(unittest.TestCase):
    def make_window(self):
        code = main_window_methods()["scan_devices"]
        callbacks = []
        class Async:
            @staticmethod
            def run(work, done=None, failed=None, **_kwargs):
                callbacks.append((work, done, failed))
        namespace = {"Async": Async, "castctl": SimpleNamespace(scan=lambda: []),
                     "dlna": SimpleNamespace(discover=lambda: [])}
        exec(compile("class Window:\n" + textwrap.indent(code, "    "), "<scanning-test>", "exec"), namespace)
        window = namespace["Window"]()
        window._closing = False
        window._scan_again = False
        window.scan_busy = False
        published = []
        window.device_detail = SimpleNamespace(set_text=lambda text: None)
        window._scan_done = lambda result: published.append(result)
        window._scan_failed = lambda message: published.append(("error", message))
        return window, callbacks, published

    def test_rescan_does_not_publish_superseded_results(self):
        window, callbacks, published = self.make_window()
        window.scan_devices()
        self.assertEqual(len(callbacks), 1)
        window.scan_devices()  # same window while first discovery is running
        self.assertEqual(len(callbacks), 1)
        callbacks[0][1]((["stale"], []))
        self.assertEqual(published, [])
        self.assertEqual(len(callbacks), 2)
        callbacks[1][1]((["current"], []))
        self.assertEqual(published, [(["current"], [])])

    def test_close_drops_scan_callbacks_without_touching_window(self):
        window, callbacks, published = self.make_window()
        window.scan_devices()
        window._closing = True
        callbacks[0][1]((["stale"], []))
        self.assertEqual(published, [])
        self.assertFalse(window.scan_busy)

    def test_failed_earlier_scan_starts_queued_refresh(self):
        window, callbacks, published = self.make_window()
        window.scan_devices()
        window.scan_devices()
        callbacks[0][2]("old scan failed")
        self.assertEqual(published, [])
        self.assertEqual(len(callbacks), 2)
        callbacks[1][1]((["new"], []))
        self.assertEqual(published, [(["new"], [])])


if __name__ == "__main__":
    unittest.main()
