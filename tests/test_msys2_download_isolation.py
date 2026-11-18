"""Offline MSYS2 downloader race, size and cleanup tests (no installer runs)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup"))
import bootstrap


NAME = "msys2-x86_64-20261118.exe"
BINARY = b"checksum-verified MSYS2 fixture"
SHA = hashlib.sha256(BINARY).hexdigest()
ASSETS = json.dumps({"assets": [
    {"name": NAME, "browser_download_url": "https://github.com/msys2/installer"},
    {"name": NAME + ".sha256", "browser_download_url": "https://github.com/msys2/checksum"},
]}).encode()


def fake_url(request, timeout=None, *, payload=BINARY, expected=SHA, barrier=None,
             break_installer=False):
    url = getattr(request, "full_url", request)
    if "api.github.com" in url:
        return io.BytesIO(ASSETS)
    if "checksum" in url:
        return io.BytesIO((expected + "  " + NAME).encode())
    if barrier is not None:
        barrier.wait(timeout=5)
    if break_installer:
        class Interrupted(io.BytesIO):
            def __init__(self):
                super().__init__(payload)
                self.first = True

            def read(self, count=-1):
                if self.first:
                    self.first = False
                    return super().read(3)
                raise OSError("connection interrupted")
        return Interrupted()
    return io.BytesIO(payload)


class IsolatedInstallerDownloadTests(unittest.TestCase):
    def stage(self, root: str):
        # Make random staging directories inside a disposable test directory,
        # without mocking the temp-path generator's randomness or permissions.
        real_mkdtemp = tempfile.mkdtemp
        return mock.patch.object(
            bootstrap.tempfile, "mkdtemp",
            side_effect=lambda *, prefix: real_mkdtemp(prefix=prefix, dir=root),
        )

    def test_two_downloads_never_share_an_executable_or_temp_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            barrier = threading.Barrier(2)
            with self.stage(folder), mock.patch.object(
                bootstrap.urllib.request, "urlopen",
                side_effect=lambda req, timeout=None: fake_url(
                    req, timeout, barrier=barrier,
                ),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    a = executor.submit(bootstrap.download_verified_msys2)
                    b = executor.submit(bootstrap.download_verified_msys2)
                    one, two = a.result(timeout=10), b.result(timeout=10)
                self.assertNotEqual(one, two)
                self.assertNotEqual(one.parent, two.parent)
                self.assertEqual(one.read_bytes(), BINARY)
                self.assertEqual(two.read_bytes(), BINARY)
                self.assertTrue(one.parent.name.startswith("smoothcast-msys2-"))
                self.assertTrue(two.parent.name.startswith("smoothcast-msys2-"))

    def test_interrupted_transfer_removes_private_partial_download(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.stage(folder), mock.patch.object(
                bootstrap.urllib.request, "urlopen",
                side_effect=lambda req, timeout=None: fake_url(
                    req, timeout, break_installer=True,
                ),
            ):
                with self.assertRaisesRegex(bootstrap.SetupError, "interrupted"):
                    bootstrap.download_verified_msys2()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_mismatch_and_oversized_payload_leave_no_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            for expected, limit, phrase in (
                ("0" * 64, 100, "SHA-256 mismatch"),
                (SHA, 5, "safe download size limit"),
            ):
                with self.subTest(phrase=phrase), self.stage(folder), \
                     mock.patch.object(bootstrap, "MAX_MSYS2_DOWNLOAD_BYTES", limit), \
                     mock.patch.object(
                         bootstrap.urllib.request, "urlopen",
                         side_effect=lambda req, timeout=None: fake_url(
                             req, timeout, expected=expected,
                         ),
                     ):
                    with self.assertRaisesRegex(bootstrap.SetupError, phrase):
                        bootstrap.download_verified_msys2()
                    self.assertEqual(list(Path(folder).iterdir()), [])

    def test_unverified_download_is_never_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "msys64"
            with mock.patch.object(bootstrap, "msys2_root", return_value=root), \
                 mock.patch.object(bootstrap, "python_ok", return_value=False), \
                 mock.patch.object(bootstrap, "check_tools", return_value=[]), \
                 mock.patch.object(bootstrap, "download_verified_msys2",
                                   side_effect=bootstrap.SetupError("invalid checksum")), \
                 mock.patch.object(bootstrap, "checked_run") as execute:
                with self.assertRaisesRegex(bootstrap.SetupError, "invalid checksum"):
                    bootstrap.install_windows()
                execute.assert_not_called()

    def test_successful_install_always_retires_private_staging_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "msys64"
            staged = Path(folder) / "smoothcast-msys2-test" / NAME
            staged.parent.mkdir()
            staged.write_bytes(BINARY)
            shell = root / "usr" / "bin" / "bash.exe"
            def installed(_argv, **kwargs):
                shell.parent.mkdir(parents=True, exist_ok=True)
                shell.touch()
            with mock.patch.object(bootstrap, "msys2_root", return_value=root), \
                 mock.patch.object(bootstrap, "python_ok", return_value=True), \
                 mock.patch.object(bootstrap, "works", return_value=True), \
                 mock.patch.object(bootstrap, "check_tools", return_value=[]), \
                 mock.patch.object(bootstrap, "download_verified_msys2",
                                   return_value=staged), \
                 mock.patch.object(bootstrap, "checked_run", side_effect=installed) as execute, \
                 mock.patch.object(bootstrap, "pick_runtime",
                                   return_value=root / "ucrt64/bin/python.exe"):
                bootstrap.install_windows()
            self.assertFalse(staged.parent.exists())
            self.assertEqual(execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
