"""DLNA discovery must isolate failing LAN responders without failing silently."""
from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace
import unittest
from unittest import mock

import dlna


def result(value=None, error=None):
    future = Future()
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(value)
    return future


def renderer(name, host="192.168.1.5"):
    return SimpleNamespace(name=name, host=host,
                           transport_url=f"http://{host}/av")


class DiscoveryFailureTests(unittest.TestCase):
    def test_broken_descriptions_do_not_hide_healthy_receivers_or_leak_urls(self):
        malformed = result(error=RuntimeError(
            "private/media/film.mkv token=MY_SECRET http://192.168.1.20/desc"))
        healthy = result(renderer("Working"))
        duplicate = result(renderer("Duplicate name, same origin"))
        other = result(renderer("A different receiver", "192.168.1.6"))
        with self.assertLogs("dlna", level="WARNING") as captured:
            found = dlna._collect_responsive_renderers([
                malformed, healthy, duplicate, other, result(None)])
        self.assertEqual([r.name for r in found], ["A different receiver", "Working"])
        self.assertEqual(len(captured.output), 1)
        self.assertIn("1 failed renderer inspections", captured.output[0])
        self.assertNotIn("MY_SECRET", captured.output[0])
        self.assertNotIn("192.168.1.20", captured.output[0])
        self.assertNotIn("film.mkv", captured.output[0])

    def test_many_failed_responders_are_reported_once(self):
        futures = [result(error=ValueError(f"untrusted {n}")) for n in range(50)]
        with self.assertLogs("dlna", level="WARNING") as captured:
            self.assertEqual(dlna._collect_responsive_renderers(futures), [])
        self.assertEqual(len(captured.output), 1)
        self.assertIn("50 failed", captured.output[0])

    def test_no_warning_when_every_response_is_valid(self):
        with mock.patch.object(dlna.logging.getLogger("dlna"), "warning") as warning:
            found = dlna._collect_responsive_renderers([result(renderer("TV"))])
        self.assertEqual([r.name for r in found], ["TV"])
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
