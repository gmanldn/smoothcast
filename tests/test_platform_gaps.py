"""The per-platform known-gap register stays accurate and never touches Linux (#258)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import conftest
import platform_gaps

TESTS = Path(__file__).resolve().parent


def fake_item(nodeid: str):
    item = SimpleNamespace(nodeid=nodeid, markers=[])
    item.add_marker = item.markers.append
    return item


class RegisterTests(unittest.TestCase):
    def test_only_the_native_desktop_platforms_have_entries(self):
        self.assertEqual(set(platform_gaps.GAPS), {"darwin", "win32"})   # never "linux"

    def test_every_entry_names_a_real_test_and_gives_a_reason(self):
        for platform, entries in platform_gaps.GAPS.items():
            for nodeid, reason in entries.items():
                with self.subTest(platform=platform, test=nodeid):
                    path, *names = nodeid.split("::")
                    source = (TESTS / path).read_text("utf-8")
                    self.assertTrue(names, "id must be file::...::test")
                    for name in names:
                        self.assertIn(name, source, f"{nodeid}: stale entry, {name} not found")
                    self.assertGreater(len(reason.split()), 3, "give a specific reason")

    def test_entries_are_exact_test_ids_not_whole_files(self):
        for entries in platform_gaps.GAPS.values():
            for nodeid in entries:
                self.assertGreaterEqual(nodeid.count("::"), 1, nodeid)    # keeps passing tests running

    def test_windows_library_index_is_never_silently_skipped_again(self):
        # #304 is fixed. A register with zero known product bugs is a success,
        # not a reason to demand a permanent defect in the codebase.
        for platform, entries in platform_gaps.GAPS.items():
            for nodeid in entries:
                self.assertFalse(nodeid.startswith("test_library_index.py::"),
                                 f"{platform} is suppressing a real media-index regression: {nodeid}")


class HookTests(unittest.TestCase):
    # A Windows-only entry (not also registered for macOS), so cross-platform checks are exact.
    ENTRY = next(k for k in platform_gaps.GAPS["win32"] if k not in platform_gaps.GAPS["darwin"])

    def run_hook(self, platform: str, nodeid: str):
        item = fake_item(nodeid)
        with mock.patch("sys.platform", platform):
            conftest.pytest_collection_modifyitems(None, [item])
        return item.markers

    def test_a_registered_test_is_skipped_only_on_its_platform_with_the_reason(self):
        markers = self.run_hook("win32", "tests/" + self.ENTRY)
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].name, "skip")
        self.assertIn("known win32 gap (#258)", markers[0].kwargs["reason"])
        self.assertEqual(self.run_hook("linux", "tests/" + self.ENTRY), [])   # Linux skips nothing
        self.assertEqual(self.run_hook("darwin", "tests/" + self.ENTRY), [])  # not a darwin entry

    def test_unregistered_tests_are_never_skipped(self):
        for platform in ("linux", "win32", "darwin"):
            self.assertEqual(self.run_hook(platform, "tests/test_core.py::SomeTest::test_x"), [])

    def test_linux_collection_skips_nothing_from_the_register(self):
        for entries in platform_gaps.GAPS.values():
            for nodeid in entries:
                self.assertEqual(self.run_hook("linux", "tests/" + nodeid), [])


if __name__ == "__main__":
    unittest.main()
